"""Configuration loading for ARIUS.

Config is JSON by default (zero dependencies, works everywhere). If PyYAML
happens to be installed, ``.yaml``/``.yml`` files are also accepted.

The loader intentionally keeps a permissive shape: unknown keys are ignored
so the config format can grow without breaking older files.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

DEFAULT_CONFIG_NAMES = ("config.json", "config.yaml", "config.yml")


@dataclass
class LLMConfig:
    """Which language model backend to talk to."""

    backend: str = "echo"  # "echo" (offline) | "anthropic"
    model: str = "claude-sonnet-5"
    api_key_env: str = "ANTHROPIC_API_KEY"
    max_tokens: int = 1024
    temperature: float = 0.4

    @property
    def api_key(self) -> str | None:
        return os.environ.get(self.api_key_env) or None


@dataclass
class PersonaConfig:
    """How the assistant presents itself."""

    honorific: str = "님"  # form of address appended to the user's name (Korean)
    tone: str = "formal"  # "formal" | "casual"
    style_notes: str = (
        "차분하고 정중하며 유능하다. 군더더기 없이 핵심을 말하고, "
        "필요하면 먼저 제안한다. 영화 속 인공지능 비서처럼 신뢰감 있게 응대한다."
    )


@dataclass
class EmbeddingsConfig:
    """How text is turned into vectors for similarity-based recall."""

    backend: str = "hashing"  # "hashing" (offline, no deps) | "sentence-transformers"
    model: str = "paraphrase-multilingual-MiniLM-L12-v2"
    dim: int = 512  # only used by the hashing backend


@dataclass
class VoiceConfig:
    """Spoken input/output. Everything here is optional and degrades gracefully."""

    enabled: bool = False  # speak replies aloud
    listen: bool = False  # take input from the microphone
    language: str = "ko-KR"
    rate: int = 180  # words per minute (pyttsx3 / say)
    voice_name: str = ""  # substring of a preferred OS voice name, e.g. "Yuna"


@dataclass
class UserConfig:
    """A person the assistant recognizes."""

    username: str
    role: str = "user"
    display_name: str = ""
    passphrase_hash: str = ""  # empty => login without a passphrase (local trust)

    def __post_init__(self) -> None:
        if not self.display_name:
            self.display_name = self.username


@dataclass
class AriusConfig:
    assistant_name: str = "ARIUS"
    language: str = "ko"
    data_dir: str = "~/.arius"
    llm: LLMConfig = field(default_factory=LLMConfig)
    persona: PersonaConfig = field(default_factory=PersonaConfig)
    embeddings: EmbeddingsConfig = field(default_factory=EmbeddingsConfig)
    voice: VoiceConfig = field(default_factory=VoiceConfig)
    users: list[UserConfig] = field(default_factory=list)
    # Username assumed when nobody has logged in. GUEST role unless overridden.
    default_user: str = "guest"

    @property
    def resolved_data_dir(self) -> Path:
        return Path(os.path.expanduser(self.data_dir))

    def user(self, username: str) -> UserConfig | None:
        for u in self.users:
            if u.username == username:
                return u
        return None

    def with_users(self, users: list[UserConfig]) -> "AriusConfig":
        return replace(self, users=users)


def _coerce(data: dict[str, Any]) -> AriusConfig:
    llm = LLMConfig(**{k: v for k, v in (data.get("llm") or {}).items() if k in LLMConfig.__dataclass_fields__})
    persona = PersonaConfig(
        **{k: v for k, v in (data.get("persona") or {}).items() if k in PersonaConfig.__dataclass_fields__}
    )
    embeddings = EmbeddingsConfig(
        **{k: v for k, v in (data.get("embeddings") or {}).items() if k in EmbeddingsConfig.__dataclass_fields__}
    )
    voice = VoiceConfig(**{k: v for k, v in (data.get("voice") or {}).items() if k in VoiceConfig.__dataclass_fields__})
    users = [
        UserConfig(**{k: v for k, v in u.items() if k in UserConfig.__dataclass_fields__})
        for u in (data.get("users") or [])
    ]
    nested = {"llm", "persona", "users", "embeddings", "voice"}
    top = {k: v for k, v in data.items() if k in AriusConfig.__dataclass_fields__ and k not in nested}
    return AriusConfig(llm=llm, persona=persona, embeddings=embeddings, voice=voice, users=users, **top)


def _read_raw(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    if path.suffix in {".yaml", ".yml"}:
        try:
            import yaml  # type: ignore
        except ImportError as exc:  # pragma: no cover - depends on optional dep
            raise RuntimeError(
                f"{path} is YAML but PyYAML is not installed. "
                "Run `pip install pyyaml` or use a JSON config instead."
            ) from exc
        return yaml.safe_load(text) or {}
    return json.loads(text)


def find_config(explicit: str | None = None, search_dir: str | os.PathLike[str] = ".") -> Path | None:
    """Locate a config file, honoring an explicit path first."""
    if explicit:
        p = Path(explicit).expanduser()
        return p if p.exists() else None
    base = Path(search_dir)
    for name in DEFAULT_CONFIG_NAMES:
        candidate = base / name
        if candidate.exists():
            return candidate
    return None


def load_config(path: str | None = None, search_dir: str | os.PathLike[str] = ".") -> AriusConfig:
    """Load configuration, falling back to safe defaults when none is found."""
    found = find_config(path, search_dir)
    if found is None:
        return AriusConfig()
    return _coerce(_read_raw(found))


def config_to_dict(config: AriusConfig) -> dict[str, Any]:
    """Serialize a config back to a plain dict (for `arius init`)."""
    return {
        "assistant_name": config.assistant_name,
        "language": config.language,
        "data_dir": config.data_dir,
        "default_user": config.default_user,
        "llm": {
            "backend": config.llm.backend,
            "model": config.llm.model,
            "api_key_env": config.llm.api_key_env,
            "max_tokens": config.llm.max_tokens,
            "temperature": config.llm.temperature,
        },
        "persona": {
            "honorific": config.persona.honorific,
            "tone": config.persona.tone,
            "style_notes": config.persona.style_notes,
        },
        "embeddings": {
            "backend": config.embeddings.backend,
            "model": config.embeddings.model,
            "dim": config.embeddings.dim,
        },
        "voice": {
            "enabled": config.voice.enabled,
            "listen": config.voice.listen,
            "language": config.voice.language,
            "rate": config.voice.rate,
            "voice_name": config.voice.voice_name,
        },
        "users": [
            {
                "username": u.username,
                "role": u.role,
                "display_name": u.display_name,
                "passphrase_hash": u.passphrase_hash,
            }
            for u in config.users
        ],
    }
