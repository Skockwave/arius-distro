"""Anthropic Claude backend (optional).

Requires the ``anthropic`` package and an API key. Both are looked up lazily
so the rest of ARIUS runs without them. See the README for setup.
"""

from __future__ import annotations

from arius.llm.base import LLMBackend, Message


class AnthropicBackend(LLMBackend):
    name = "anthropic"

    def __init__(
        self,
        model: str = "claude-sonnet-5",
        api_key: str | None = None,
        max_tokens: int = 1024,
        temperature: float = 0.4,
    ) -> None:
        self.model = model
        self.api_key = api_key
        self.max_tokens = max_tokens
        self.temperature = temperature
        self._client = None
        self._import_error: str | None = None
        try:
            import anthropic  # type: ignore

            if api_key:
                self._client = anthropic.Anthropic(api_key=api_key)
            else:
                # Falls back to ANTHROPIC_API_KEY in the environment.
                self._client = anthropic.Anthropic()
        except ImportError:
            self._import_error = (
                "`anthropic` 패키지가 설치되지 않았습니다. `pip install anthropic` 후 다시 시도하십시오."
            )
        except Exception as exc:  # pragma: no cover - client construction edge cases
            self._import_error = f"Anthropic 클라이언트 초기화 실패: {exc}"

    @property
    def available(self) -> bool:
        return self._client is not None and (self.api_key is not None or self._client is not None)

    def unavailable_reason(self) -> str | None:
        if self._import_error:
            return self._import_error
        if self._client is None:
            return "Anthropic 클라이언트를 사용할 수 없습니다. API 키를 확인하십시오."
        return None

    def generate(self, system: str, messages: list[Message]) -> str:
        if self._client is None:
            raise RuntimeError(self.unavailable_reason() or "Anthropic backend unavailable")
        resp = self._client.messages.create(
            model=self.model,
            max_tokens=self.max_tokens,
            temperature=self.temperature,
            system=system,
            messages=[{"role": m.role, "content": m.content} for m in messages],
        )
        parts = [block.text for block in resp.content if getattr(block, "type", None) == "text"]
        return "\n".join(parts).strip()
