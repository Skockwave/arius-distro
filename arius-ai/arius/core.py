"""The ARIUS orchestrator.

Ties together configuration, the permission manager, memory, the LLM backend,
and the skill registry, and exposes a single ``handle(text)`` entry point.

Routing for each input:
  1. If a skill matches:
       - the session holds its capability  -> run the skill
       - otherwise                          -> a polite, in-persona refusal
  2. Otherwise -> free conversation via the LLM backend, with recalled facts
     and recent history folded into the prompt.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from arius.config import AriusConfig, config_to_dict, find_config, load_config
from arius.agent.loop import AgentLoop, AgentResult
from arius.agent.tools import ToolContext, build_registry
from arius.embeddings import build_embedder
from arius.llm import LLMBackend, Message, build_backend
from arius.memory import Memory
from arius.modes import MODES, get_mode
from arius.privacy import redact
from arius.permissions import (
    AccessDenied,
    AuthenticationError,
    PermissionManager,
    Session,
)
from arius.persona import build_system_prompt
from arius.skills import SkillContext, SkillRegistry
from arius.skills.builtin import default_skills


@dataclass
class Reply:
    """A response plus a little metadata about how it was produced."""

    text: str
    source: str  # "skill:<name>" | "llm:<backend>" | "system"


class Arius:
    def __init__(
        self,
        config: AriusConfig | None = None,
        *,
        memory: Memory | None = None,
        backend: LLMBackend | None = None,
        registry: SkillRegistry | None = None,
    ) -> None:
        self.config = config or AriusConfig()
        self.permissions = PermissionManager.from_config(self.config)
        self.embedder = build_embedder(self.config)
        if memory is None:
            memory = Memory(self._default_db_path(), embedder=self.embedder)
        elif memory.embedder is None:
            memory.embedder = self.embedder
        self.memory = memory
        # Embed pre-existing data once (e.g. a DB created before vectors existed).
        self.memory.ensure_index()
        self.backend = backend or build_backend(self.config)
        self.registry = registry or SkillRegistry(default_skills())
        self.session: Session = self.permissions.guest_session()
        self.tools = build_registry()
        # Set by the front end: how to ask a human before a state-changing tool runs,
        # and where agent progress lines go. Defaults are safe (deny / silent).
        self.confirm: Callable[[str], bool] = lambda desc: False
        self.notify: Callable[[str], None] = lambda msg: None
        # Called with the new mode key after set_mode() (the CLI pauses the heartbeat in sleep mode).
        self.on_mode_change: Callable[[str], None] = lambda key: None
        self.config_path: Path | None = None
        self.memory.seed_policies(self.config.agent.policies)

    # -- construction helpers ------------------------------------------------
    @classmethod
    def from_path(cls, config_path: str | None = None, search_dir: str = ".") -> "Arius":
        inst = cls(load_config(config_path, search_dir))
        inst.config_path = find_config(config_path, search_dir)
        return inst

    def save_config(self) -> bool:
        """Persist the in-memory config (auto_allow changes etc.). False when no file is known."""
        if self.config_path is None:
            return False
        self.config_path.write_text(json.dumps(config_to_dict(self.config), ensure_ascii=False, indent=2), encoding="utf-8")
        return True

    def _default_db_path(self) -> str:
        d = self.config.resolved_data_dir
        return str(d / "memory.db")

    # -- authentication ------------------------------------------------------
    def login(self, username: str, passphrase: str | None = None) -> Session:
        self.session = self.permissions.authenticate(username, passphrase)
        return self.session

    def login_guest(self) -> Session:
        self.session = self.permissions.guest_session()
        return self.session

    def logout(self) -> None:
        self.session = self.permissions.guest_session()

    @property
    def current_user_label(self) -> str:
        u = self.session.user
        return f"{u.display_name} ({u.role.label})"

    # -- main entry point ----------------------------------------------------
    def handle(self, text: str) -> Reply:
        return self.handle_for(self.session, text, channel="console")

    def handle_for(self, session: Session, text: str, channel: str = "console") -> Reply:
        """Answer on behalf of any session (REPL, Discord member, voice)."""
        text = (text or "").strip()
        if not text:
            return Reply("무슨 말씀이신지 다시 한 번 말씀해 주십시오.", "system")

        skill = self.registry.find(text)
        if skill is not None:
            if not session.can(skill.capability):
                return Reply(
                    self._refusal(skill.capability, session),
                    f"denied:{skill.name}",
                )
            ctx = SkillContext(
                session=session,
                memory=self.memory,
                config=self.config,
                permissions=self.permissions,
                registry=self.registry,
                tools=self.tool_context(session),
                agent=lambda goal, _s=session: self.run_agent(_s, goal).final,
                arius=self,
            )
            try:
                result = skill.run(ctx, text)
            except AccessDenied as exc:
                return Reply(str(exc), f"denied:{skill.name}")
            self._record(session, text, result)
            return Reply(result, f"skill:{skill.name}")

        if (
            self.config.agent.route_chat
            and self.backend.name != "echo"
            and self.is_agent_request(text)
            and session.can("agent.run")
        ):
            result = self.run_agent(session, text)
            self._record(session, text, result.final)
            return Reply(result.final, "agent")

        return self._chat(text, session, channel)

    def _record(self, session: Session, user_text: str, reply_text: str) -> None:
        """Conversation log — with secrets masked, per the memory rules."""
        self.memory.add_message(session.user.username, "user", redact(user_text))
        self.memory.add_message(session.user.username, "assistant", redact(reply_text))

    # -- autonomous agent ---------------------------------------------------
    _AGENT_TRIGGER = re.compile(
        r"(^/do\b|^작업\s*[:：]|(줘|주세요|주라|해\s*봐|해라|해줄래|할래|해\s*주게|부탁해)\s*[.!~?]*$)"
    )

    @classmethod
    def is_agent_request(cls, text: str) -> bool:
        return bool(cls._AGENT_TRIGGER.search(text.strip()))

    def tool_context(self, session: Session | None = None) -> ToolContext:
        return ToolContext(config=self.config, memory=self.memory, session=session or self.session, notify=self.notify)

    def agent_loop(self, session: Session | None = None, **overrides) -> AgentLoop:
        a = self.config.agent
        mode = get_mode(self.current_mode())
        kwargs = dict(
            autonomy=a.autonomy,
            max_steps=min(a.max_steps, mode.max_steps),
            auto_allow=a.auto_allow,
            confirm=self.confirm,
            on_event=self.notify,
            persona=(
                f"당신은 '{self.config.assistant_name}'입니다. {self.config.persona.style_notes} "
                f"현재 운영 모드: {mode.label} — {mode.prompt} "
                "보고는 '완료했습니다. …' / '실행하지 않았습니다. 이유: … 다음 조치: …' 형식을 지킵니다."
            ),
        )
        kwargs.update(overrides)
        return AgentLoop(self.backend, self.tools, self.tool_context(session), **kwargs)

    def run_agent(self, session: Session, goal: str, context_note: str = "") -> AgentResult:
        goal = re.sub(r"^(/do\b|작업\s*[:：])\s*", "", goal.strip())
        self.memory.log_agent("task", goal[:200])
        return self.agent_loop(session).run(goal, context_note)

    # -- conversation --------------------------------------------------------
    def _chat(self, text: str, session: Session | None = None, channel: str = "console") -> Reply:
        session = session or self.session
        username = session.user.username
        mode_key = self.current_mode()
        mode = get_mode(mode_key)
        recalled = []
        if session.can("memory.read"):
            recalled = self.memory.recall_facts(username, text, limit=mode.recall)

        system = build_system_prompt(self.config, session, recalled, channel=channel, mood=self.current_mood(), mode=mode_key)
        history = self.memory.recent_messages(username, limit=4 if mode_key in ("fast", "sleep") else 10)
        messages = [Message(role=m["role"], content=m["content"]) for m in history if m["role"] in ("user", "assistant")]
        messages.append(Message(role="user", content=text))

        try:
            reply_text = self.backend.generate(system, messages)
        except Exception as exc:  # keep the REPL alive on backend errors
            reply_text = f"응답 생성 중 오류가 발생했습니다: {exc}"

        degraded = getattr(self.backend, "_degraded_reason", None)
        if degraded:
            reply_text += f"\n\n(알림: 요청하신 백엔드를 쓸 수 없어 오프라인 모드로 답했습니다 — {degraded})"

        self._record(session, text, reply_text)
        return Reply(reply_text, f"llm:{self.backend.name}")

    # -- mood ------------------------------------------------------------------
    MOOD_KEY = "mood"

    def current_mood(self) -> str:
        """The assistant's feeling, set by events (heartbeat transitions) or the user."""
        for f in self.memory.list_facts("__arius__"):
            if f.key == self.MOOD_KEY:
                return f.value
        return ""

    def set_mood(self, mood: str) -> None:
        self.memory.learn_fact("__arius__", self.MOOD_KEY, mood, source="system")

    # -- operating mode --------------------------------------------------------
    MODE_KEY = "mode"

    def current_mode(self) -> str:
        for f in self.memory.list_facts("__arius__"):
            if f.key == self.MODE_KEY and f.value in MODES:
                return f.value
        return self.config.agent.default_mode if self.config.agent.default_mode in MODES else "accurate"

    def set_mode(self, key: str) -> str:
        if key not in MODES:
            raise ValueError(f"unknown mode: {key}")
        self.memory.learn_fact("__arius__", self.MODE_KEY, key, source="system")
        self.on_mode_change(key)
        return key

    # -- helpers -------------------------------------------------------------
    def _refusal(self, capability: str, session: Session | None = None) -> str:
        session = session or self.session
        return (
            "실행하지 않았습니다.\n"
            f"이유: '{capability}' 권한이 필요한데, {session.user.display_name}{self.config.persona.honorific}의 "
            f"현재 등급은 '{session.role.label}'입니다.\n"
            "다음 조치: 권한이 있는 계정으로 로그인하거나('/login <아이디>') 오너에게 권한 상향을 요청해 주세요."
        )

    def close(self) -> None:
        self.memory.close()


__all__ = ["Arius", "Reply", "AuthenticationError"]
