"""LLM backend abstraction.

A backend takes a system prompt plus a running list of messages and returns
the assistant's next reply as plain text. Keeping the contract this small
lets the offline echo backend and a real API backend be fully swappable.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class Message:
    role: str  # "user" | "assistant"
    content: str


class LLMBackend(ABC):
    name: str = "base"

    @abstractmethod
    def generate(self, system: str, messages: list[Message]) -> str:
        """Return the assistant's reply to the latest message."""

    @property
    def available(self) -> bool:
        """Whether this backend can actually serve a request right now."""
        return True

    def unavailable_reason(self) -> str | None:
        return None
