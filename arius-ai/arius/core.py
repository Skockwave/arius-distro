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

from dataclasses import dataclass

from arius.config import AriusConfig, load_config
from arius.embeddings import build_embedder
from arius.llm import LLMBackend, Message, build_backend
from arius.memory import Memory
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

    # -- construction helpers ------------------------------------------------
    @classmethod
    def from_path(cls, config_path: str | None = None, search_dir: str = ".") -> "Arius":
        return cls(load_config(config_path, search_dir))

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
        text = (text or "").strip()
        if not text:
            return Reply("무슨 말씀이신지 다시 한 번 말씀해 주십시오.", "system")

        skill = self.registry.find(text)
        if skill is not None:
            if not self.session.can(skill.capability):
                return Reply(
                    self._refusal(skill.capability),
                    f"denied:{skill.name}",
                )
            ctx = SkillContext(
                session=self.session,
                memory=self.memory,
                config=self.config,
                permissions=self.permissions,
                registry=self.registry,
            )
            try:
                result = skill.run(ctx, text)
            except AccessDenied as exc:
                return Reply(str(exc), f"denied:{skill.name}")
            self.memory.add_message(self.session.user.username, "user", text)
            self.memory.add_message(self.session.user.username, "assistant", result)
            return Reply(result, f"skill:{skill.name}")

        return self._chat(text)

    # -- conversation --------------------------------------------------------
    def _chat(self, text: str) -> Reply:
        username = self.session.user.username
        recalled = []
        if self.session.can("memory.read"):
            recalled = self.memory.recall_facts(username, text, limit=4)

        system = build_system_prompt(self.config, self.session, recalled)
        history = self.memory.recent_messages(username, limit=10)
        messages = [Message(role=m["role"], content=m["content"]) for m in history if m["role"] in ("user", "assistant")]
        messages.append(Message(role="user", content=text))

        try:
            reply_text = self.backend.generate(system, messages)
        except Exception as exc:  # keep the REPL alive on backend errors
            reply_text = f"응답 생성 중 오류가 발생했습니다: {exc}"

        degraded = getattr(self.backend, "_degraded_reason", None)
        if degraded:
            reply_text += f"\n\n(알림: 요청하신 백엔드를 쓸 수 없어 오프라인 모드로 답했습니다 — {degraded})"

        self.memory.add_message(username, "user", text)
        self.memory.add_message(username, "assistant", reply_text)
        return Reply(reply_text, f"llm:{self.backend.name}")

    # -- helpers -------------------------------------------------------------
    def _refusal(self, capability: str) -> str:
        return (
            f"죄송하지만 그 작업에는 '{capability}' 권한이 필요합니다. "
            f"현재 {self.session.user.display_name}{self.config.persona.honorific}의 "
            f"등급은 '{self.session.role.label}'이라 실행할 수 없습니다. "
            "권한이 있는 계정으로 로그인하시거나 오너에게 권한 상향을 요청하십시오."
        )

    def close(self) -> None:
        self.memory.close()


__all__ = ["Arius", "Reply", "AuthenticationError"]
