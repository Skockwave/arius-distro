"""Role-based access control (RBAC) for ARIUS.

This is the module that makes the assistant *controllable by authority*:
every skill declares a required capability, and the assistant refuses to run
anything the current session's role does not grant.

Design:
  * Roles are ordered (OWNER > ADMIN > OPERATOR > USER > GUEST).
  * Each role maps to a set of capabilities. OWNER holds the wildcard "*".
  * Users authenticate with an optional PBKDF2-hashed passphrase.
  * A Session couples an authenticated user to their live role.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import time
from dataclasses import dataclass, field
from enum import IntEnum

from arius.config import AriusConfig, UserConfig


class Role(IntEnum):
    """Authority levels, ordered from least to most privileged."""

    GUEST = 0
    USER = 1
    OPERATOR = 2
    ADMIN = 3
    OWNER = 4

    @classmethod
    def parse(cls, value: str | "Role" | int) -> "Role":
        if isinstance(value, Role):
            return value
        if isinstance(value, int):
            return cls(value)
        try:
            return cls[value.strip().upper()]
        except KeyError as exc:
            raise ValueError(f"알 수 없는 권한 등급입니다: {value!r}") from exc

    @property
    def label(self) -> str:
        return {
            Role.GUEST: "게스트",
            Role.USER: "사용자",
            Role.OPERATOR: "운영자",
            Role.ADMIN: "관리자",
            Role.OWNER: "오너",
        }[self]


# --- Capabilities -----------------------------------------------------------
# Capability strings are namespaced "area.action". "*" is a wildcard held by
# the owner. A skill asks for exactly one capability.

WILDCARD = "*"

CAP_CHAT = "chat"
CAP_MEMORY_READ = "memory.read"
CAP_MEMORY_WRITE = "memory.write"
CAP_SYSTEM_INFO = "system.info"
CAP_SYSTEM_EXEC = "system.exec"  # dangerous: run shell commands
CAP_PROJECT_READ = "project.read"
CAP_PROJECT_MANAGE = "project.manage"
CAP_USER_MANAGE = "user.manage"  # add/remove users, change roles
CAP_WEB_LEARN = "web.learn"  # fetch web pages and store their content
CAP_WEB_READ = "web.read"  # recall previously learned web knowledge
CAP_FILES_READ = "files.read"  # list/read files inside the agent sandbox
CAP_FILES_WRITE = "files.write"  # write/move/delete files inside the sandbox
CAP_MC_READ = "mc.read"  # ping the Minecraft server, read the manifest
CAP_MC_ADMIN = "mc.admin"  # RCON console commands
CAP_DISCORD_READ = "discord.read"  # read recent channel messages (bot)
CAP_DISCORD_ANNOUNCE = "discord.announce"  # post/edit announcements
CAP_AGENT_RUN = "agent.run"  # ask the agent to do a task / run a heartbeat
CAP_AGENT_MANAGE = "agent.manage"  # policies, autonomy level, on/off


ROLE_CAPABILITIES: dict[Role, set[str]] = {
    Role.OWNER: {WILDCARD},
    Role.ADMIN: {
        CAP_CHAT,
        CAP_MEMORY_READ,
        CAP_MEMORY_WRITE,
        CAP_SYSTEM_INFO,
        CAP_SYSTEM_EXEC,
        CAP_PROJECT_READ,
        CAP_PROJECT_MANAGE,
        CAP_WEB_LEARN,
        CAP_WEB_READ,
        CAP_FILES_READ,
        CAP_FILES_WRITE,
        CAP_MC_READ,
        CAP_MC_ADMIN,
        CAP_DISCORD_READ,
        CAP_DISCORD_ANNOUNCE,
        CAP_AGENT_RUN,
        CAP_AGENT_MANAGE,
    },
    Role.OPERATOR: {
        CAP_CHAT,
        CAP_MEMORY_READ,
        CAP_MEMORY_WRITE,
        CAP_SYSTEM_INFO,
        CAP_PROJECT_READ,
        CAP_PROJECT_MANAGE,
        CAP_WEB_LEARN,
        CAP_WEB_READ,
        CAP_FILES_READ,
        CAP_MC_READ,
        CAP_DISCORD_READ,
        CAP_DISCORD_ANNOUNCE,
        CAP_AGENT_RUN,
    },
    Role.USER: {
        CAP_CHAT,
        CAP_MEMORY_READ,
        CAP_MEMORY_WRITE,
        CAP_PROJECT_READ,
        CAP_WEB_READ,
        CAP_MC_READ,
    },
    Role.GUEST: {
        CAP_CHAT,
    },
}


def capabilities_for(role: Role) -> set[str]:
    return set(ROLE_CAPABILITIES.get(role, set()))


def role_has_capability(role: Role, capability: str) -> bool:
    caps = ROLE_CAPABILITIES.get(role, set())
    return WILDCARD in caps or capability in caps


# --- Passphrase hashing -----------------------------------------------------

_PBKDF2_ITERATIONS = 200_000


def hash_passphrase(passphrase: str, *, salt: str | None = None, iterations: int = _PBKDF2_ITERATIONS) -> str:
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", passphrase.encode("utf-8"), bytes.fromhex(salt), iterations)
    return f"pbkdf2_sha256${iterations}${salt}${digest.hex()}"


def verify_passphrase(passphrase: str, stored: str) -> bool:
    try:
        algo, iters, salt, hexhash = stored.split("$")
        if algo != "pbkdf2_sha256":
            return False
        digest = hashlib.pbkdf2_hmac("sha256", passphrase.encode("utf-8"), bytes.fromhex(salt), int(iters))
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(digest.hex(), hexhash)


# --- Users & sessions -------------------------------------------------------


@dataclass
class User:
    username: str
    role: Role
    display_name: str = ""
    passphrase_hash: str = ""

    def __post_init__(self) -> None:
        if not self.display_name:
            self.display_name = self.username

    @property
    def requires_passphrase(self) -> bool:
        return bool(self.passphrase_hash)

    @classmethod
    def from_config(cls, uc: UserConfig) -> "User":
        return cls(
            username=uc.username,
            role=Role.parse(uc.role),
            display_name=uc.display_name,
            passphrase_hash=uc.passphrase_hash,
        )


@dataclass
class Session:
    user: User
    authenticated_at: float = field(default_factory=time.time)

    @property
    def role(self) -> Role:
        return self.user.role

    @property
    def capabilities(self) -> set[str]:
        return capabilities_for(self.role)

    def can(self, capability: str) -> bool:
        return role_has_capability(self.role, capability)


class AccessDenied(Exception):
    """Raised when a session lacks a required capability."""

    def __init__(self, capability: str, role: Role) -> None:
        self.capability = capability
        self.role = role
        super().__init__(f"권한 부족: '{capability}' 기능은 현재 등급({role.label})에서 사용할 수 없습니다.")


class AuthenticationError(Exception):
    """Raised on a failed login."""


class PermissionManager:
    """Holds the known users and issues sessions after authentication."""

    GUEST = User(username="guest", role=Role.GUEST, display_name="게스트")

    def __init__(self, users: list[User] | None = None) -> None:
        self._users: dict[str, User] = {}
        for user in users or []:
            self._users[user.username] = user

    @classmethod
    def from_config(cls, config: AriusConfig) -> "PermissionManager":
        return cls([User.from_config(uc) for uc in config.users])

    # -- lookups
    def get(self, username: str) -> User | None:
        return self._users.get(username)

    def users(self) -> list[User]:
        return list(self._users.values())

    # -- authentication
    def authenticate(self, username: str, passphrase: str | None = None) -> Session:
        user = self._users.get(username)
        if user is None:
            raise AuthenticationError(f"등록되지 않은 사용자입니다: {username!r}")
        if user.requires_passphrase:
            if not passphrase or not verify_passphrase(passphrase, user.passphrase_hash):
                raise AuthenticationError("암호가 일치하지 않습니다.")
        return Session(user=user)

    def guest_session(self) -> Session:
        return Session(user=self.GUEST)

    # -- mutation (used by the user-admin skill; gated by CAP_USER_MANAGE)
    def add_user(self, user: User) -> None:
        if user.username in self._users:
            raise ValueError(f"이미 존재하는 사용자입니다: {user.username}")
        self._users[user.username] = user

    def set_role(self, username: str, role: Role) -> None:
        user = self._users.get(username)
        if user is None:
            raise ValueError(f"등록되지 않은 사용자입니다: {username}")
        user.role = role

    def remove_user(self, username: str) -> None:
        self._users.pop(username, None)

    def require(self, session: Session, capability: str) -> None:
        """Raise AccessDenied unless the session holds the capability."""
        if not session.can(capability):
            raise AccessDenied(capability, session.role)
