"""LLM backends and the factory that builds one from config."""

from __future__ import annotations

from arius.config import AriusConfig
from arius.llm.base import LLMBackend, Message

__all__ = ["LLMBackend", "Message", "build_backend"]


def build_backend(config: AriusConfig) -> LLMBackend:
    """Construct the configured backend, falling back to echo if unavailable."""
    backend = config.llm.backend.lower()
    if backend == "anthropic":
        from arius.llm.anthropic_backend import AnthropicBackend

        be = AnthropicBackend(
            model=config.llm.model,
            api_key=config.llm.api_key,
            max_tokens=config.llm.max_tokens,
            temperature=config.llm.temperature,
        )
        if be.available:
            return be
        # Graceful degradation: keep the assistant usable offline.
        from arius.llm.echo_backend import EchoBackend

        fallback = EchoBackend(config.assistant_name, config.persona.honorific)
        fallback._degraded_reason = be.unavailable_reason()  # type: ignore[attr-defined]
        return fallback

    if backend == "ollama":
        from arius.llm.ollama_backend import OllamaBackend
        from arius.ollama import DEFAULT_CHAT_MODEL

        model = config.llm.model
        # A leftover cloud model name means "use the local default".
        if not model or model.lower().startswith("claude"):
            model = DEFAULT_CHAT_MODEL
        be = OllamaBackend(
            model=model,
            base_url=config.llm.base_url,
            max_tokens=config.llm.max_tokens,
            temperature=config.llm.temperature,
        )
        if be.available:
            return be
        from arius.llm.echo_backend import EchoBackend

        fallback = EchoBackend(config.assistant_name, config.persona.honorific)
        fallback._degraded_reason = be.unavailable_reason()  # type: ignore[attr-defined]
        return fallback

    from arius.llm.echo_backend import EchoBackend

    return EchoBackend(config.assistant_name, config.persona.honorific)
