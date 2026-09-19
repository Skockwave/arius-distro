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

from arius import minecraft as mc
from arius import sysinfo
from arius.agent.loop import AgentLoop
from arius.agent.tools import SYSTEM_USER, ToolContext
from arius.discord import DiscordError, format_announcement

_PCT = re.compile(r"(\d{2,3})\s*%")
_ALERTS_KEY = "alerts.active"


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
        alerts = self.health_alerts(snap, status)
        for a in self._new_alerts(alerts):
            self.on_event(a)
        if alerts:
            note += "\n감지된 문제:\n" + "\n".join(f"- {a}" for a in alerts)

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

    # -- built-in health checks (no policy needed) -----------------------------
    def health_alerts(self, snap: dict, status) -> list[str]:
        """Disk / memory / CPU / repeated log errors / stale backup, each with cause → impact → action."""
        a = self.ctx.config.agent
        out: list[str] = []
        for d in snap.get("disks", []):
            if d.get("used_pct", 0) >= a.alert_disk_pct:
                out.append(f"⚠️ 디스크 {d['path']} {d['used_pct']}% 사용 (여유 {d.get('free_gb', '?')}GB) — 원인: 용량 부족 / 영향: 월드 저장·백업 실패 가능 / 권장: 다운로드·백업 폴더 정리 제안")
        mem = snap.get("memory", {})
        if mem.get("used_pct", 0) >= a.alert_memory_pct:
            out.append(f"⚠️ 메모리 {mem['used_pct']}% 사용 — 원인: 프로그램 과다 / 영향: 렉·서버 지연 / 권장: 상위 프로세스 확인 후 종료 여부 결정")
        load = (snap.get("cpu") or {}).get("load_pct")
        if load is not None and load >= a.alert_cpu_pct:
            out.append(f"⚠️ CPU 부하 {load}% — 원인: 무거운 작업 / 영향: 서버 TPS 저하 / 권장: 작업 관리자에서 원인 확인")
        sd = self.ctx.server_dir()
        if sd and status.online:
            errors = mc.tail_log(sd, 200, r"\bERROR\b|Exception")
            n = 0 if errors.startswith(("(", "로그")) else len(errors.splitlines())
            if n >= a.alert_log_errors:
                out.append(f"⚠️ 서버 로그에 오류 {n}건 반복 — 원인: 플러그인/모드 예외 가능 / 영향: 기능 오류·크래시 위험 / 권장: '서버 로그 오류' 로 확인")
        latest = self.ctx.latest_backup()
        bdir = self.ctx.backup_dir()
        if latest is not None:
            age_h = (time.time() - latest.stat().st_mtime) / 3600
            if age_h > a.alert_backup_hours:
                out.append(f"⚠️ 최근 백업이 {age_h:.0f}시간 전 ({latest.name}) — 영향: 장애 시 복구 지점 오래됨 / 권장: '서버 백업'")
        elif bdir is not None and bdir.is_dir():
            out.append("⚠️ 백업 폴더에 zip 백업이 없습니다 — 권장: '서버 백업'")
        return out

    def _new_alerts(self, alerts: list[str]) -> list[str]:
        """Only announce an alert when it first appears (state kept in memory), so a 10-minute
        heartbeat does not repeat the same warning all day."""
        keys = {a.split(" — ")[0] for a in alerts}
        prev_raw = {f.key: f.value for f in self.ctx.memory.list_facts(SYSTEM_USER)}.get(_ALERTS_KEY, "")
        prev = set(prev_raw.split("\x1f")) if prev_raw else set()
        if keys != prev:
            if keys:
                self.ctx.memory.learn_fact(SYSTEM_USER, _ALERTS_KEY, "\x1f".join(sorted(keys)), source="system")
            else:
                self.ctx.memory.forget_fact(SYSTEM_USER, _ALERTS_KEY)
        return [a for a in alerts if a.split(" — ")[0] not in prev]

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
        self.ctx.memory.learn_fact(SYSTEM_USER, "mood", "안도와 기쁨 — 서버가 다시 살아났다" if online else "걱정 — 서버가 꺼져 있다")
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
