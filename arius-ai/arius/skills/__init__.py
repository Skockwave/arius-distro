"""Skill framework: matchable, permission-gated capabilities.

A skill is a small unit of behavior the assistant can invoke instead of (or
before) calling the language model. Each skill declares:
  * a name and description (for the help listing),
  * the capability the caller must hold, and
  * a matcher that decides whether an input is for this skill.

The registry tries skills in priority order; the first match whose capability
the session holds runs. Anything unmatched falls through to the LLM.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from arius.config import AriusConfig
from arius.memory import Memory
from arius.permissions import PermissionManager, Session


@dataclass
class SkillContext:
    """Everything a skill needs to do its job."""

    session: Session
    memory: Memory
    config: AriusConfig
    permissions: PermissionManager
    registry: "SkillRegistry"
    tools: object | None = None  # arius.agent.tools.ToolContext when available
    agent: object | None = None  # callable(goal) -> report, runs the agent loop
    arius: object | None = None  # the orchestrator (modes, config saving); None in bare tests


class Skill(ABC):
    name: str = "skill"
    description: str = ""
    capability: str = "chat"
    priority: int = 100  # lower runs first

    @abstractmethod
    def matches(self, text: str) -> bool:
        """Whether this skill should handle the given input."""

    @abstractmethod
    def run(self, ctx: SkillContext, text: str) -> str:
        """Handle the input and return a reply."""


class SkillRegistry:
    def __init__(self, skills: list[Skill] | None = None) -> None:
        self._skills: list[Skill] = []
        for s in skills or []:
            self.register(s)

    def register(self, skill: Skill) -> None:
        self._skills.append(skill)
        self._skills.sort(key=lambda s: s.priority)

    def all(self) -> list[Skill]:
        return list(self._skills)

    def available_for(self, session: Session) -> list[Skill]:
        return [s for s in self._skills if session.can(s.capability)]

    def find(self, text: str) -> Skill | None:
        """First skill (by priority) whose matcher accepts the text."""
        for skill in self._skills:
            if skill.matches(text):
                return skill
        return None
