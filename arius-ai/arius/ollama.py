"""Tiny Ollama HTTP client helpers (standard library only).

Ollama (https://ollama.com) serves open models on your own machine at
http://localhost:11434. Both the chat backend and the local embedder talk to
it through these helpers, and tests inject a fake transport instead.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from collections.abc import Callable

DEFAULT_BASE_URL = "http://localhost:11434"
DEFAULT_CHAT_MODEL = "llama3.1"
DEFAULT_EMBED_MODEL = "bge-m3"  # multilingual; good for Korean

# transport(method, path, json_payload_or_None, timeout_seconds) -> parsed JSON
Transport = Callable[[str, str, dict | None, float], dict]


def http_json(base_url: str = DEFAULT_BASE_URL) -> Transport:
    base = base_url.rstrip("/")

    def _call(method: str, path: str, payload: dict | None, timeout: float) -> dict:
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        req = urllib.request.Request(
            base + path, data=data, method=method, headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 (local server)
            body = resp.read().decode("utf-8")
        return json.loads(body) if body else {}

    return _call


def has_model(names: set[str] | list[str], model: str) -> bool:
    """Ollama tags carry ':latest' etc.; 'llama3.1' should match 'llama3.1:latest'."""
    names = set(names)
    if model in names:
        return True
    if ":" not in model:
        return any(n.split(":")[0] == model for n in names)
    return False


def probe(transport: Transport, model: str, base_url: str, timeout: float = 3.0) -> str | None:
    """Return None if the server is up and the model is pulled, else a Korean reason."""
    try:
        tags = transport("GET", "/api/tags", None, timeout)
    except Exception as exc:  # connection refused, DNS, timeout, bad JSON ...
        return (
            f"Ollama 서버에 연결할 수 없습니다 ({base_url}). "
            f"Ollama를 설치하고 실행 중인지 확인하십시오. ({exc.__class__.__name__}: {exc})"
        )
    models = tags.get("models")
    if isinstance(models, list):
        names = {m.get("name", "") for m in models if isinstance(m, dict)}
        if not has_model(names, model):
            return f"모델 '{model}'이(가) 준비되어 있지 않습니다. 터미널에서 `ollama pull {model}` 을 실행하십시오."
    return None
