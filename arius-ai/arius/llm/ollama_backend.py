"""Ollama backend: run open models entirely on your own machine.

No API key, no cloud, no extra Python packages. Install Ollama, pull a model
(`ollama pull llama3.1` — or `exaone3.5` / `qwen2.5` for strong Korean), and
set `llm.backend = "ollama"` in config.json.
"""

from __future__ import annotations

from arius.llm.base import LLMBackend, Message
from arius.ollama import DEFAULT_BASE_URL, DEFAULT_CHAT_MODEL, Transport, http_json, probe


class OllamaBackend(LLMBackend):
    name = "ollama"

    def __init__(
        self,
        model: str = DEFAULT_CHAT_MODEL,
        base_url: str = DEFAULT_BASE_URL,
        max_tokens: int = 1024,
        temperature: float = 0.4,
        timeout: float = 180.0,
        transport: Transport | None = None,
    ) -> None:
        self.model = model
        self.base_url = base_url
        self.max_tokens = max_tokens
        self.temperature = temperature
        self.timeout = timeout
        self._transport = transport or http_json(base_url)
        self._reason = probe(self._transport, model, base_url)

    @property
    def available(self) -> bool:
        return self._reason is None

    def unavailable_reason(self) -> str | None:
        return self._reason

    def generate(self, system: str, messages: list[Message]) -> str:
        if not self.available:
            raise RuntimeError(self._reason or "Ollama backend unavailable")
        payload = {
            "model": self.model,
            "stream": False,
            "messages": [{"role": "system", "content": system}]
            + [{"role": m.role, "content": m.content} for m in messages],
            "options": {"temperature": self.temperature, "num_predict": self.max_tokens},
        }
        resp = self._transport("POST", "/api/chat", payload, self.timeout)
        message = resp.get("message") or {}
        return str(message.get("content", "")).strip()
