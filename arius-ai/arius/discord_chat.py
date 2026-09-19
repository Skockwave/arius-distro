"""Discord conversation mode: ARIUS talks with people in chosen channels.

Polls the channel over the REST API (no websocket gateway needed), answers
messages that mention the bot or call it by name (or every message when
chat_mention_only is false), and replies in the emotional, human-like persona.
Members chat under the RBAC role `discord.chat_role` (default: user), so they
can talk and ask about the server but cannot run admin tools.
"""

from __future__ import annotations

import re
import threading
import time
from collections.abc import Callable

from arius.discord import DiscordBot, DiscordError

ReplyFn = Callable[[str, dict], str]  # (text, raw message) -> reply or ""


class DiscordChat:
    def __init__(
        self,
        bot: DiscordBot,
        reply_fn: ReplyFn,
        channels: list[str],
        *,
        wake_words: list[str] | None = None,
        mention_only: bool = True,
        poll_seconds: int = 4,
        on_event: Callable[[str], None] | None = None,
    ) -> None:
        self.bot = bot
        self.reply_fn = reply_fn
        self.channels = [c for c in channels if c]
        self.wake_words = [w for w in (wake_words or []) if w]
        self.mention_only = mention_only
        self.poll_seconds = max(2, int(poll_seconds))
        self.on_event = on_event or (lambda m: None)
        self.bot_id: str = ""
        self.last_ids: dict[str, str | None] = {}
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self.replies_sent = 0

    # -- setup: learn who we are and start from "now" so history is not answered
    def bootstrap(self) -> None:
        me = self.bot.me()
        self.bot_id = str(me.get("id", ""))
        for ch in self.channels:
            latest = self.bot.messages_after(ch, None, limit=1)
            self.last_ids[ch] = str(latest[-1]["id"]) if latest else None

    def _addressed(self, msg: dict) -> tuple[bool, str]:
        content = str(msg.get("content", ""))
        mentioned = any(str(u.get("id")) == self.bot_id for u in msg.get("mentions") or [])
        text = re.sub(rf"<@!?{re.escape(self.bot_id)}>", " ", content) if self.bot_id else content
        called = False
        for w in self.wake_words:
            if w and w.lower() in text.lower():
                called = True
                text = re.sub(re.escape(w), " ", text, flags=re.IGNORECASE)
        text = " ".join(text.split())
        return (mentioned or called), text

    def poll_once(self) -> int:
        sent = 0
        for ch in self.channels:
            try:
                msgs = self.bot.messages_after(ch, self.last_ids.get(ch))
            except DiscordError as exc:
                self.on_event(f"디스코드 조회 실패: {exc}")
                if "rate limit" in str(exc):
                    time.sleep(10)
                continue
            for m in msgs:
                self.last_ids[ch] = str(m.get("id"))
                author = m.get("author") or {}
                if author.get("bot") or str(author.get("id")) == self.bot_id:
                    continue
                addressed, text = self._addressed(m)
                if self.mention_only and not addressed:
                    continue
                if not text:
                    text = "안녕"
                self.bot.typing(ch)
                try:
                    reply = self.reply_fn(text, m)
                except Exception as exc:  # never let one bad message stop the loop
                    self.on_event(f"응답 생성 실패: {exc}")
                    continue
                if not reply:
                    continue
                try:
                    self.bot.send(ch, reply[:2000])
                    sent += 1
                    self.replies_sent += 1
                    self.on_event(f"디스코드 답장 → {author.get('username', '?')}: {reply[:60]}")
                except DiscordError as exc:
                    self.on_event(f"디스코드 전송 실패: {exc}")
        return sent

    # -- background thread
    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="arius-discord-chat", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    @property
    def running(self) -> bool:
        return bool(self._thread and self._thread.is_alive() and not self._stop.is_set())

    def _loop(self) -> None:
        try:
            self.bootstrap()
        except DiscordError as exc:
            self.on_event(f"디스코드 봇 시작 실패: {exc}")
            return
        self.on_event(f"디스코드 대화 모드 시작 (채널 {len(self.channels)}개, 봇 ID {self.bot_id})")
        while not self._stop.is_set():
            try:
                self.poll_once()
            except Exception as exc:
                self.on_event(f"디스코드 대화 오류: {exc}")
            if self._stop.wait(self.poll_seconds):
                break
