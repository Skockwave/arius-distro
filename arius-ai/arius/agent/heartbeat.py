"""Periodic self-check: snapshot the machine and the Minecraft server, then let
the model (or, offline, a small rule engine) decide whether any standing policy
calls for action. Runs once (`run_once`) or forever in a background thread.
"""

from __future__ import annotations

import json
import re
import threading
import time
from collections.abc import Callable

from arius import sysinfo
from arius.agent.loop import AgentLoop
from arius.agent.tools import SYSTEM_USER, ToolContext
from arius.discord import DiscordError, format_announcement

_PCT = re.compile(r"(\d{2,3})\s*%")


class Heartbeat:
    def __init__(
        self,
        loop_factory: Callable[[], AgentLoop],
        ctx: ToolContext,
        *,
        interval_minutes: int = 10,
        on_event: Callable[[str], None] | None = None,
        notify_discord: bool = False,
    ) -> None:
        self.loop_factory = loop_factory
        self.ctx = ctx
        self.interval = max(1, int(interval_minutes)) * 60
        self.on_event = on_event or (lambda m: None)
        self.notify_discord = notify_discord
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self.last_run: float = 0.0
        self.last_report: str = ""

    def observe(self) -> tuple[str, dict, object]:
        snap = self.ctx.snapshot_fn()
        host, port = self.ctx.mc_host()
        status = self.ctx.pinger(host, port)
        note = sysinfo.describe(snap) + "\n마인크래프트: " + status.summary().replace("\n", " ")
        return note, snap, status

    def run_once(self) -> str:
        self.last_run = time.time()
        try:
            note, snap, status = self.observe()
        except Exception as exc:
            self.ctx.memory.log_agent("error", "관찰 실패", str(exc))
            return f"관찰 실패: {exc}"

        transition = self._server_transition(status.online)
        if transition:
            note += f"\n이벤트: {transition}"
            self.on_event(transition)

        loop = self.loop_factory()
        if loop.backend.name == "echo":
            report = self._rules(snap, status, transition, loop)
        else:
            result = loop.run(
                "정기 점검(하트비트)입니다. 아래 현재 상황과 상시 정책을 보고, 정책이 요구하는 조치가 있을 때만 도구를 사용하십시오. "
                "조치가 필요 없으면 final 로 '이상 없음'과 한 줄 근거만 답하십시오.",
                context_note=note,
            )
            report = result.final
            if result.actions_taken and self.notify_discord:
                self._discord(f"자동 조치 {result.actions_taken}건", result.transcript())
        self.last_report = report
        self.ctx.memory.log_agent("heartbeat", (report.splitlines() or ["(빈 보고)"])[0][:200], report)
        return report

    # -- offline rule engine (no LLM): thresholds and server-down policies only
    def _rules(self, snap: dict, status, transition: str, loop: AgentLoop) -> str:
        actions: list[str] = []
        policies = [p["text"] for p in self.ctx.memory.list_policies(enabled_only=True)]
        name = self.ctx.config.minecraft.name
        for text in policies:
            low = text.lower()
            m = _PCT.search(text)
            threshold = int(m.group(1)) if m else None
            if "디스크" in text and threshold is not None:
                for d in snap.get("disks", []):
                    if d["used_pct"] >= threshold:
                        actions.append(self._act(loop, "notify_user", {"message": f"⚠️ 디스크 {d['path']} 사용량 {d['used_pct']}% (정책: {text})"}))
            if "메모리" in text and threshold is not None and snap.get("memory", {}).get("used_pct", 0) >= threshold:
                actions.append(self._act(loop, "notify_user", {"message": f"⚠️ 메모리 사용량 {snap['memory']['used_pct']}% (정책: {text})"}))
            if "서버" in text and any(k in low for k in ("꺼지", "오프라인", "다운", "죽")) and not status.online:
                if any(k in low for k in ("재시작", "다시 켜", "켜줘", "시작")):
                    actions.append(self._act(loop, "minecraft_start", {"wait": False}))
                if any(k in low for k in ("디스코드", "공지")):
                    actions.append(self._act(loop, "discord_announce", {"title": "서버 상태", "body": f"🔴 {name} 가 오프라인입니다. 확인 중입니다."}))
                if "알려" in low:
                    actions.append(self._act(loop, "notify_user", {"message": f"🔴 {name} 오프라인 (정책: {text})"}))
        if transition and "온라인" in transition and any(("디스코드" in p or "공지" in p) for p in policies):
            actions.append(self._act(loop, "discord_announce", {"title": "서버 상태", "body": f"🟢 {name} 가 다시 온라인입니다."}))
        actions = [a for a in actions if a]
        return "이상 없음 (규칙 점검, 언어 모델 미연결)" if not actions else "규칙 기반 조치:\n" + "\n".join(f"- {a}" for a in actions)

    def _act(self, loop: AgentLoop, tool_name: str, args: dict) -> str:
        tool = loop.tools.get(tool_name)
        if tool is None:
            return ""
        allowed, why = loop._gate(tool, args)
        if not allowed:
            self.ctx.memory.log_agent("denied", f"{tool_name} 거부", why)
            return f"{tool_name}: 거부됨 ({why})"
        try:
            out = tool.handler(self.ctx, args)
        except Exception as exc:
            self.ctx.memory.log_agent("error", f"{tool_name} 오류", str(exc))
            return f"{tool_name}: 오류 {exc}"
        self.ctx.memory.log_agent("action", tool_name, json.dumps(args, ensure_ascii=False)[:300] + " → " + str(out)[:300])
        self.on_event(f"{tool_name} 실행: {str(out)[:120]}")
        return f"{tool_name}: {(str(out).splitlines() or [''])[0][:160]}"

    def _server_transition(self, online: bool) -> str:
        key = "mc.last_online"
        prev = {f.key: f.value for f in self.ctx.memory.list_facts(SYSTEM_USER)}.get(key)
        now = "1" if online else "0"
        self.ctx.memory.learn_fact(SYSTEM_USER, key, now)
        if prev is None or prev == now:
            return ""
        name = self.ctx.config.minecraft.name
        return f"🟢 {name} 가 온라인이 되었습니다." if online else f"🔴 {name} 가 오프라인이 되었습니다."

    def _discord(self, title: str, body: str) -> None:
        try:
            self.ctx.discord().announce(format_announcement(title, body, self.ctx.config.assistant_name))
        except DiscordError as exc:
            self.ctx.memory.log_agent("error", "디스코드 알림 실패", str(exc))

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="arius-heartbeat", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    @property
    def running(self) -> bool:
        return bool(self._thread and self._thread.is_alive() and not self._stop.is_set())

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                report = self.run_once()
                self.on_event("점검: " + ((report.splitlines() or ["(없음)"])[0]))
            except Exception as exc:  # never let the thread die
                self.on_event(f"점검 오류: {exc}")
            if self._stop.wait(self.interval):
                break
