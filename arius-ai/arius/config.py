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

    backend: str = "echo"  # "echo" (offline) | "anthropic" (cloud) | "ollama" (local model)
    model: str = "claude-sonnet-5"  # for ollama: an Ollama model name, e.g. "llama3.1", "exaone3.5"
    api_key_env: str = "ANTHROPIC_API_KEY"
    base_url: str = "http://localhost:11434"  # ollama server
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
    emotional: bool = True  # express feelings naturally, talk like a warm human
    style_notes: str = (
        "차분하고 정중하며 유능하다. 군더더기 없이 핵심을 말하고, "
        "필요하면 먼저 제안한다. 영화 속 인공지능 비서처럼 신뢰감 있게 응대한다."
    )


@dataclass
class EmbeddingsConfig:
    """How text is turned into vectors for similarity-based recall."""

    backend: str = "hashing"  # "hashing" (offline, no deps) | "sentence-transformers" | "ollama"
    model: str = "paraphrase-multilingual-MiniLM-L12-v2"  # for ollama: e.g. "bge-m3", "nomic-embed-text"
    dim: int = 512  # only used by the hashing backend
    base_url: str = "http://localhost:11434"  # ollama server


@dataclass
class VoiceConfig:
    """Spoken input/output. Everything here is optional and degrades gracefully."""

    enabled: bool = False  # speak replies aloud
    listen: bool = False  # take input from the microphone
    language: str = "ko-KR"
    rate: int = 180  # words per minute (pyttsx3 / say)
    voice_name: str = ""  # substring of a preferred OS voice name, e.g. "Yuna"
    wake_words: list[str] = field(default_factory=list)  # empty = the assistant's name
    awake_seconds: int = 20  # after answering, keep listening without the wake word


@dataclass
class AgentConfig:
    """The autonomous agent: observes the machine/server, thinks with the LLM, acts
    through a small set of purpose-built tools. There is deliberately no tool for
    arbitrary shell commands or file deletion — the agent can only do what is
    listed here, and state changes need confirmation unless explicitly allowed."""

    enabled: bool = False  # start the heartbeat automatically with the REPL
    autonomy: str = "supervised"  # "observe" | "supervised" | "autonomous"
    interval_minutes: int = 10  # heartbeat period
    max_steps: int = 8  # tool calls per run
    route_chat: bool = True  # send "...해줘" / "/do" requests through the agent
    notify_discord: bool = False  # post heartbeat actions to Discord too
    policies: list[str] = field(default_factory=list)  # standing natural-language rules
    # Folders the agent may READ (list/read files). Nothing is ever written or deleted.
    read_paths: list[str] = field(default_factory=list)
    # In "autonomous" mode, only these state-changing tools run without asking.
    auto_allow: list[str] = field(
        default_factory=lambda: ["discord_announce", "minecraft_say", "minecraft_command", "minecraft_start", "remember"]
    )
    # Console commands the agent may send over RCON (first word). Everything else is refused.
    rcon_allow: list[str] = field(
        default_factory=lambda: ["list", "tps", "save-all", "say", "tell", "msg", "whitelist", "kick", "time", "weather", "seed", "version", "plugins"]
    )


@dataclass
class MinecraftConfig:
    """The Minecraft server ARIUS looks after (defaults come from distribution.json)."""

    name: str = "마인크래프트 서버"  # display name used in reports and announcements
    host: str = "localhost"  # "host" or "host:port" of the server to ping
    port: int = 25565
    server_dir: str = ""  # folder with server.properties; empty = detect from the running JVM
    rcon_host: str = ""  # empty = same as host
    rcon_port: int = 25575
    rcon_password: str = ""  # or set the env var named below
    rcon_password_env: str = "ARIUS_RCON_PASSWORD"
    distribution_path: str = "../distribution.json"
    start_command: str = ""  # optional: how to start the server on this machine

    @property
    def resolved_rcon_password(self) -> str:
        return self.rcon_password or os.environ.get(self.rcon_password_env, "")


@dataclass
class DiscordConfig:
    """Announcements via an incoming webhook (simplest) or a bot token + channel."""

    webhook_url: str = ""
    webhook_url_env: str = "ARIUS_DISCORD_WEBHOOK"
    bot_token: str = ""
    bot_token_env: str = "ARIUS_DISCORD_TOKEN"
    channel_id: str = ""  # announcement channel when using the bot
    username: str = "ARIUS"  # display name for webhook posts
    # Conversation mode (bot token required): reply to people in these channels.
    chat_channels: list[str] = field(default_factory=list)
    chat_mention_only: bool = True  # only answer when @mentioned or called by name
    chat_role: str = "user"  # RBAC role Discord members get when chatting
    poll_seconds: int = 4  # how often to look for new messages

    @property
    def resolved_webhook(self) -> str:
        return self.webhook_url or os.environ.get(self.webhook_url_env, "")

    @property
    def resolved_token(self) -> str:
        return self.bot_token or os.environ.get(self.bot_token_env, "")


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
    agent: AgentConfig = field(default_factory=AgentConfig)
    minecraft: MinecraftConfig = field(default_factory=MinecraftConfig)
    discord: DiscordConfig = field(default_factory=DiscordConfig)
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
    agent = AgentConfig(**{k: v for k, v in (data.get("agent") or {}).items() if k in AgentConfig.__dataclass_fields__})
    minecraft = MinecraftConfig(
        **{k: v for k, v in (data.get("minecraft") or {}).items() if k in MinecraftConfig.__dataclass_fields__}
    )
    discord = DiscordConfig(
        **{k: v for k, v in (data.get("discord") or {}).items() if k in DiscordConfig.__dataclass_fields__}
    )
    users = [
        UserConfig(**{k: v for k, v in u.items() if k in UserConfig.__dataclass_fields__})
        for u in (data.get("users") or [])
    ]
    nested = {"llm", "persona", "users", "embeddings", "voice", "agent", "minecraft", "discord"}
    top = {k: v for k, v in data.items() if k in AriusConfig.__dataclass_fields__ and k not in nested}
    return AriusConfig(
        llm=llm, persona=persona, embeddings=embeddings, voice=voice,
        agent=agent, minecraft=minecraft, discord=discord, users=users, **top,
    )


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
            "base_url": config.llm.base_url,
            "max_tokens": config.llm.max_tokens,
            "temperature": config.llm.temperature,
        },
        "persona": {
            "honorific": config.persona.honorific,
            "tone": config.persona.tone,
            "emotional": config.persona.emotional,
            "style_notes": config.persona.style_notes,
        },
        "embeddings": {
            "backend": config.embeddings.backend,
            "model": config.embeddings.model,
            "dim": config.embeddings.dim,
            "base_url": config.embeddings.base_url,
        },
        "voice": {
            "enabled": config.voice.enabled,
            "listen": config.voice.listen,
            "language": config.voice.language,
            "rate": config.voice.rate,
            "voice_name": config.voice.voice_name,
            "wake_words": list(config.voice.wake_words),
            "awake_seconds": config.voice.awake_seconds,
        },
        "agent": {
            "enabled": config.agent.enabled,
            "autonomy": config.agent.autonomy,
            "interval_minutes": config.agent.interval_minutes,
            "max_steps": config.agent.max_steps,
            "route_chat": config.agent.route_chat,
            "notify_discord": config.agent.notify_discord,
            "policies": list(config.agent.policies),
            "read_paths": list(config.agent.read_paths),
            "auto_allow": list(config.agent.auto_allow),
            "rcon_allow": list(config.agent.rcon_allow),
        },
        "minecraft": {
            "name": config.minecraft.name,
            "host": config.minecraft.host,
            "port": config.minecraft.port,
            "server_dir": config.minecraft.server_dir,
            "rcon_host": config.minecraft.rcon_host,
            "rcon_port": config.minecraft.rcon_port,
            "rcon_password": config.minecraft.rcon_password,
            "rcon_password_env": config.minecraft.rcon_password_env,
            "distribution_path": config.minecraft.distribution_path,
            "start_command": config.minecraft.start_command,
        },
        "discord": {
            "webhook_url": config.discord.webhook_url,
            "webhook_url_env": config.discord.webhook_url_env,
            "bot_token": config.discord.bot_token,
            "bot_token_env": config.discord.bot_token_env,
            "channel_id": config.discord.channel_id,
            "username": config.discord.username,
            "chat_channels": list(config.discord.chat_channels),
            "chat_mention_only": config.discord.chat_mention_only,
            "chat_role": config.discord.chat_role,
            "poll_seconds": config.discord.poll_seconds,
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
