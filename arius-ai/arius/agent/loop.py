"""Think → act loop with an autonomy gate.

Backend-agnostic: the model answers with one JSON object per turn —
  {"thought": "...", "action": "<tool>", "args": {...}}   to use a tool, or
  {"thought": "...", "final": "<report>"}                to finish —
so it works with Claude, any Ollama model, or anything else that writes JSON.

Autonomy levels:
  observe     - read-only tools; anything else is refused and logged
  supervised  - every state change asks the confirm() callback (default)
  autonomous  - tools listed in agent.auto_allow run without asking; all other
                state changes still ask. "danger" tools (stop/restart) always
                ask unless explicitly listed.
RBAC and the tools' own refusals (allowlists, read-only paths) apply at every level.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass, field

from arius.agent.tools import Refused, Tool, ToolContext, tools_prompt
from arius.llm.base import LLMBackend, Message

AUTONOMY_LEVELS = ("observe", "supervised", "autonomous")

_FENCE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)


def parse_action(text: str) -> dict | None:
    """Pull the first JSON object with 'action' or 'final' out of a reply."""
    if not text:
        return None
    m = _FENCE.search(text)
    candidates = [m.group(1)] if m else []
    candidates.append(text)
    decoder = json.JSONDecoder()
    for cand in candidates:
        start = cand.find("{")
        while start != -1:
            try:
                obj, _ = decoder.raw_decode(cand[start:])
                if isinstance(obj, dict) and ("action" in obj or "final" in obj):
                    return obj
            except json.JSONDecodeError:
                pass
            start = cand.find("{", start + 1)
    return None


@dataclass
class AgentResult:
    final: str
    steps: list[dict] = field(default_factory=list)
    actions_taken: int = 0
    denied: int = 0

    def transcript(self) -> str:
        marks = {"ok": "✔", "denied": "⛔", "error": "✖", "confirm_no": "⏸"}
        return "\n".join(
            f"{marks.get(s['status'], '•')} {s['tool']}({_short(s.get('args'))}) → {_short(s.get('observation'), 160)}"
            for s in self.steps
        )


def _short(v, limit: int = 80) -> str:
    s = json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else str(v or "")
    s = " ".join(s.split())
    return s if len(s) <= limit else s[: limit - 1] + "…"


class AgentLoop:
    def __init__(
        self,
        backend: LLMBackend,
        tools: dict[str, Tool],
        ctx: ToolContext,
        *,
        autonomy: str = "supervised",
        max_steps: int = 8,
        auto_allow: tuple[str, ...] | list[str] = (),
        confirm: Callable[[str], bool] | None = None,
        on_event: Callable[[str], None] | None = None,
        persona: str = "",
    ) -> None:
        if autonomy not in AUTONOMY_LEVELS:
            raise ValueError(f"autonomy must be one of {AUTONOMY_LEVELS}")
        self.backend = backend
        self.tools = tools
        self.ctx = ctx
        self.autonomy = autonomy
        self.max_steps = max_steps
        self.auto_allow = set(auto_allow)
        self.confirm = confirm or (lambda desc: False)
        self.on_event = on_event or (lambda msg: None)
        self.persona = persona

    def system_prompt(self) -> str:
        cfg = self.ctx.config
        policies = self.ctx.memory.list_policies(enabled_only=True)
        policy_text = "\n".join(f"- {p['text']}" for p in policies) or "- (없음)"
        return (
            f"{self.persona}\n\n"
            f"당신은 {cfg.assistant_name} 의 자율 에이전트 모드입니다. 사용자의 컴퓨터 상태, 마인크래프트 서버 "
            f"'{cfg.minecraft.name}', 디스코드를 아래 도구로 관리합니다.\n"
            f"현재 자율 수준: {self.autonomy} (observe=읽기만, supervised=변경은 사용자 확인, autonomous=허용된 도구만 자동).\n"
            f"사용자의 상시 정책:\n{policy_text}\n\n"
            f"사용 가능한 도구(JSON):\n{tools_prompt(self.tools, self.ctx.session)}\n\n"
            "규칙:\n"
            "1. 매 턴 반드시 JSON 객체 하나만 출력합니다. 다른 텍스트를 붙이지 마십시오.\n"
            '   도구 사용: {"thought": "왜 이 도구인지", "action": "<도구 이름>", "args": {...}}\n'
            '   종료:     {"thought": "...", "final": "<사용자에게 보고할 내용>"}\n'
            "2. 먼저 관찰(읽기 도구)하고, 근거가 있을 때만 변경합니다. 필요 없는 조치는 하지 않습니다.\n"
            "3. 서버 중지/재시작 같은 큰 조치는 정책이 명시적으로 허용할 때만, 예고를 먼저 보냅니다.\n"
            "4. 관찰 결과에 '거부' 또는 '허용되지 않은' 이 오면 같은 도구를 반복하지 말고 다른 방법을 찾거나 종료합니다.\n"
            "5. final 보고는 한국어로, 무엇을 확인했고 무엇을 했는지 간결하게 씁니다.\n"
        )

    def _gate(self, tool: Tool, args: dict) -> tuple[bool, str]:
        if not self.ctx.session.can(tool.capability):
            return False, f"권한 없음: '{tool.capability}' (현재 등급 {self.ctx.session.role.label})"
        if tool.risk == "read":
            return True, ""
        if self.autonomy == "observe":
            return False, f"observe 모드에서는 '{tool.name}' 같은 변경 도구를 쓸 수 없습니다."
        # Per-call "always ask" (kick/ban/op...) beats auto_allow; danger tools run unasked only
        # when the owner listed them explicitly.
        must_ask = bool(tool.confirm_if and tool.confirm_if(self.ctx, args))
        if self.autonomy == "autonomous" and tool.name in self.auto_allow and not must_ask:
            return True, ""
        desc = f"실행 예정: {tool.describe(args)}\n영향: {tool.impact_text()}\n진행할까요?"
        approved = bool(self.confirm(desc))
        self._learn_decision(tool, args, approved)
        if not approved:
            return False, "사용자가 실행을 거부했습니다(또는 승인할 사람이 없음)."
        return True, ""

    def _learn_decision(self, tool: Tool, args: dict, approved: bool) -> None:
        """Behaviour learning: remember what the user approves; after three clean approvals of a
        non-dangerous tool, suggest adding it to auto_allow (never applied on its own)."""
        try:
            self.ctx.memory.record_approval(tool.name, _short(args, 120), approved)
            if not approved or tool.risk == "danger" or tool.name in self.auto_allow:
                return
            yes, no = self.ctx.memory.approval_stats(tool.name)
            if yes == 3 and no == 0:
                self.on_event(
                    f"학습: '{tool.name}' 작업을 최근 3번 모두 승인하셨어요. 다음부터 묻지 않고 실행하려면 "
                    f"'자동 허용 추가: {tool.name}' 이라고 말해 주세요. (승인 없이는 바꾸지 않습니다)"
                )
        except Exception:  # learning must never break the gate
            pass

    def run(self, goal: str, context_note: str = "") -> AgentResult:
        result = AgentResult(final="")
        if self.backend.name == "echo":
            result.final = (
                "자율 에이전트가 '생각'하려면 실제 언어 모델이 필요합니다. config 의 llm.backend 를 "
                "'anthropic'(API 키) 또는 'ollama'(로컬 모델)로 설정하십시오. 정기 점검은 규칙 기반으로 계속 동작합니다."
            )
            return result

        system = self.system_prompt()
        opening = goal if not context_note else f"{goal}\n\n[현재 상황]\n{context_note}"
        messages = [Message("user", opening)]
        for step_no in range(1, self.max_steps + 1):
            try:
                reply = self.backend.generate(system, messages)
            except Exception as exc:
                result.final = f"모델 호출 실패: {exc}"
                self.ctx.memory.log_agent("error", "모델 호출 실패", str(exc))
                return result
            action = parse_action(reply)
            if action is None or "final" in action:
                result.final = (action or {}).get("final") or reply.strip() or "(응답 없음)"
                return result

            name = str(action.get("action", "")).strip()
            args = action.get("args") or {}
            if not isinstance(args, dict):
                args = {}
            tool = self.tools.get(name)
            step = {"n": step_no, "tool": name, "args": args, "thought": action.get("thought", ""), "status": "ok", "observation": ""}
            if tool is None:
                step["status"] = "error"
                step["observation"] = f"알 수 없는 도구: {name}"
            else:
                allowed, why = self._gate(tool, args)
                if not allowed:
                    step["status"] = "confirm_no" if "거부했습니다" in why else "denied"
                    step["observation"] = f"거부됨 — {why}"
                    result.denied += 1
                    self.ctx.memory.log_agent("denied", f"{name} 거부", why)
                else:
                    try:
                        step["observation"] = tool.handler(self.ctx, args)
                        result.actions_taken += 1
                        self.ctx.memory.log_agent("action", name, _short(args, 300) + " → " + _short(step["observation"], 500))
                        self.on_event(f"{name} 실행: {_short(step['observation'], 120)}")
                    except Refused as exc:
                        step["status"] = "denied"
                        step["observation"] = f"거부됨 — {exc}"
                        result.denied += 1
                        self.ctx.memory.log_agent("denied", f"{name} 거부", str(exc))
                    except Exception as exc:  # a broken tool must not kill the loop
                        step["status"] = "error"
                        step["observation"] = f"도구 오류: {exc.__class__.__name__}: {exc}"
                        self.ctx.memory.log_agent("error", f"{name} 오류", str(exc))
            result.steps.append(step)
            messages.append(Message("assistant", reply))
            messages.append(Message("user", f"관찰 결과 ({name}):\n{step['observation']}"))

        result.final = "최대 단계 수에 도달해 중단했습니다. 지금까지의 작업:\n" + result.transcript()
        return result
