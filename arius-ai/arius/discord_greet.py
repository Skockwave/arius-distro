"""Role greeter: E.D.I.T.H. greets members the moment they are given a role.

Polls the guild member list over the REST API (no gateway), remembers who
already holds `discord.greet_role_id`, and posts a greeting for each member
that newly has it. The first poll only records the current holders, so people
who had the role before ARIUS started are not greeted again. Holders are kept
in a small JSON file so a restart does not re-greet anyone either.

The bot needs the SERVER MEMBERS INTENT (Developer Portal > Bot) to list members.
"""

from __future__ import annotations

import json
import threading
import time
from collections.abc import Callable
from pathlib import Path

from arius.discord import DiscordBot, DiscordError, DiscordWebhook

DEFAULT_GREETING = (
    "{mention}\n\n"
    "**[ E.D.I.T.H. ]**\n"
    "```\n"
    "[EVENT ] ROLE ASSIGNED : 트레이너\n"
    "[TARGET] {name}\n"
    "[STATUS] 등록 완료\n"
    "```\n"
    "신규 트레이너 등록을 확인했습니다.\n"
    "접근 권한이 부여되었습니다. 명령을 대기합니다.\n\n"
    "— *E.D.I.T.H.*"
)


def format_greeting(template: str, member: dict) -> str:
    user = member.get("user") or {}
    uid = str(user.get("id", ""))
    name = member.get("nick") or user.get("global_name") or user.get("username") or "트레이너"
    text = (template or DEFAULT_GREETING).replace("{mention}", f"<@{uid}>").replace("{name}", str(name))
    return text[:2000]


class RoleGreeter:
    def __init__(
        self,
        bot: DiscordBot,
        guild_id: str,
        role_id: str,
        *,
        webhook: DiscordWebhook | None = None,
        channel_id: str = "",
        template: str = "",
        state_path: Path | None = None,
        poll_seconds: int = 30,
        on_event: Callable[[str], None] | None = None,
    ) -> None:
        if webhook is None and not channel_id:
            raise DiscordError("인사를 보낼 곳이 없습니다. discord.greet_webhook_url 또는 greet_channel_id 를 설정하십시오.")
        self.bot = bot
        self.guild_id = str(guild_id)
        self.role_id = str(role_id)
        self.webhook = webhook
        self.channel_id = channel_id
        self.template = template
        self.state_path = state_path
        self.poll_seconds = max(10, int(poll_seconds))
        self.on_event = on_event or (lambda m: None)
        self.holders: set[str] | None = None  # None = not bootstrapped yet
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self.greeted = 0

    # -- state: who already holds the role
    def _load(self) -> set[str] | None:
        if not self.state_path or not self.state_path.exists():
            return None
        try:
            data = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        if data.get("guild_id") != self.guild_id or data.get("role_id") != self.role_id:
            return None
        return {str(i) for i in data.get("holders") or []}

    def _save(self) -> None:
        if not self.state_path or self.holders is None:
            return
        try:
            self.state_path.parent.mkdir(parents=True, exist_ok=True)
            payload = {"guild_id": self.guild_id, "role_id": self.role_id, "holders": sorted(self.holders)}
            self.state_path.write_text(json.dumps(payload), encoding="utf-8")
        except OSError:
            pass

    def _send(self, content: str) -> None:
        if self.webhook is not None:
            self.webhook.send(content)
        else:
            self.bot.send(self.channel_id, content)

    def poll_once(self) -> int:
        members = self.bot.members(self.guild_id)
        current = {
            str((m.get("user") or {}).get("id")): m
            for m in members
            if self.role_id in [str(r) for r in m.get("roles") or []] and not (m.get("user") or {}).get("bot")
        }
        if self.holders is None:
            self.holders = self._load()
        if self.holders is None:  # first run ever: remember, don't greet
            self.holders = set(current)
            self._save()
            return 0
        sent = 0
        for uid, member in current.items():
            if uid in self.holders:
                continue
            try:
                self._send(format_greeting(self.template, member))
            except DiscordError as exc:
                self.on_event(f"역할 인사 전송 실패: {exc}")
                continue  # not added to holders, so the next poll retries
            self.holders.add(uid)
            sent += 1
            self.greeted += 1
            self.on_event(f"신규 역할 인사 → {format_greeting('{name}', member)}")
        # someone who loses the role and gets it back is greeted again
        # (an empty member list is more likely a hiccup than everyone leaving)
        if members:
            self.holders &= set(current)
        self._save()
        return sent

    # -- background thread
    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="arius-discord-greet", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    @property
    def running(self) -> bool:
        return bool(self._thread and self._thread.is_alive() and not self._stop.is_set())

    def _loop(self) -> None:
        self.on_event(f"역할 인사 감시 시작 (역할 {self.role_id}, 매 {self.poll_seconds}초)")
        while not self._stop.is_set():
            try:
                self.poll_once()
            except DiscordError as exc:
                self.on_event(f"멤버 조회 실패: {exc}")
                if "rate limit" in str(exc):
                    time.sleep(30)
            except Exception as exc:
                self.on_event(f"역할 인사 오류: {exc}")
            if self._stop.wait(self.poll_seconds):
                break
