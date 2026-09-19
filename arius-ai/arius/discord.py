"""Discord announcements and light channel management, standard library only.

Two ways in:
  * Webhook  — an "incoming webhook" URL from Channel settings > Integrations.
               Simplest; can only post (and edit/delete its own posts).
  * Bot      — a bot token (Developer Portal) invited with Send/Manage Messages.
               Can post to any channel it can see, edit/delete/pin, and read
               recent messages. Uses the REST API only (no gateway/websocket).

Secrets are read from config or env (ARIUS_DISCORD_WEBHOOK / ARIUS_DISCORD_TOKEN).
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from collections.abc import Callable

API = "https://discord.com/api/v10"
USER_AGENT = "ARIUS (https://github.com/Skockwave/arius-distro, 0.1)"

# transport(method, url, headers, payload_or_None) -> (status_code, parsed_json_or_None)
Transport = Callable[[str, str, dict, dict | None], tuple[int, object]]


def http_transport(timeout: float = 15.0) -> Transport:
    def _call(method: str, url: str, headers: dict, payload: dict | None) -> tuple[int, object]:
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        req = urllib.request.Request(url, data=data, method=method, headers={"User-Agent": USER_AGENT, **headers})
        if data is not None:
            req.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 (https only)
                body = resp.read().decode("utf-8")
                return resp.status, (json.loads(body) if body else None)
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            try:
                parsed = json.loads(body) if body else None
            except json.JSONDecodeError:
                parsed = {"message": body[:300]}
            return exc.code, parsed
    return _call


class DiscordError(Exception):
    pass


def _check(status: int, body: object, what: str) -> object:
    if 200 <= status < 300:
        return body
    msg = ""
    if isinstance(body, dict):
        msg = str(body.get("message") or body)
    if status == 429:
        raise DiscordError(f"{what}: 요청이 너무 잦습니다 (rate limit). 잠시 후 다시 시도하십시오.")
    if status in (401, 403):
        raise DiscordError(f"{what}: 인증/권한 오류 ({status}). 토큰·웹훅 URL과 채널 권한을 확인하십시오. {msg}")
    raise DiscordError(f"{what}: HTTP {status} {msg}".strip())


def format_announcement(title: str, body: str, footer: str = "", mention_everyone: bool = False) -> str:
    parts = []
    if mention_everyone:
        parts.append("@everyone")
    if title:
        parts.append(f"**📢 {title.strip()}**")
    if body:
        parts.append(body.strip())
    if footer:
        parts.append(f"-# {footer.strip()}")
    text = "\n".join(parts)
    return text[:1990] + "…" if len(text) > 2000 else text


class DiscordWebhook:
    def __init__(self, url: str, username: str = "ARIUS", transport: Transport | None = None) -> None:
        if not re.match(r"^https://(?:ptb\.|canary\.)?discord(?:app)?\.com/api/webhooks/\d+/[\w-]+", url or ""):
            raise DiscordError("올바른 Discord 웹훅 URL이 아닙니다.")
        self.url = url
        self.username = username
        self._t = transport or http_transport()

    def send(self, content: str) -> dict:
        body = _check(*self._t("POST", self.url + "?wait=true", {}, {"content": content[:2000], "username": self.username}), "웹훅 전송")
        return body if isinstance(body, dict) else {}

    def edit(self, message_id: str, content: str) -> dict:
        body = _check(*self._t("PATCH", f"{self.url}/messages/{message_id}", {}, {"content": content[:2000]}), "웹훅 메시지 수정")
        return body if isinstance(body, dict) else {}

    def delete(self, message_id: str) -> None:
        _check(*self._t("DELETE", f"{self.url}/messages/{message_id}", {}, None), "웹훅 메시지 삭제")


class DiscordBot:
    def __init__(self, token: str, transport: Transport | None = None) -> None:
        if not token:
            raise DiscordError("Discord 봇 토큰이 없습니다.")
        self._h = {"Authorization": f"Bot {token}"}
        self._t = transport or http_transport()

    def send(self, channel_id: str, content: str) -> dict:
        body = _check(*self._t("POST", f"{API}/channels/{channel_id}/messages", self._h, {"content": content[:2000]}), "메시지 전송")
        return body if isinstance(body, dict) else {}

    def edit(self, channel_id: str, message_id: str, content: str) -> dict:
        body = _check(*self._t("PATCH", f"{API}/channels/{channel_id}/messages/{message_id}", self._h, {"content": content[:2000]}), "메시지 수정")
        return body if isinstance(body, dict) else {}

    def delete(self, channel_id: str, message_id: str) -> None:
        _check(*self._t("DELETE", f"{API}/channels/{channel_id}/messages/{message_id}", self._h, None), "메시지 삭제")

    def pin(self, channel_id: str, message_id: str) -> None:
        _check(*self._t("PUT", f"{API}/channels/{channel_id}/pins/{message_id}", self._h, None), "메시지 고정")

    def me(self) -> dict:
        body = _check(*self._t("GET", f"{API}/users/@me", self._h, None), "봇 정보 조회")
        return body if isinstance(body, dict) else {}

    def messages_after(self, channel_id: str, after_id: str | None, limit: int = 50) -> list[dict]:
        """Raw messages newer than after_id, oldest first (None = the latest few)."""
        q = f"?limit={max(1, min(limit, 100))}" + (f"&after={after_id}" if after_id else "")
        body = _check(*self._t("GET", f"{API}/channels/{channel_id}/messages{q}", self._h, None), "메시지 조회")
        msgs = body if isinstance(body, list) else []
        return list(reversed(msgs))

    def typing(self, channel_id: str) -> None:
        try:
            self._t("POST", f"{API}/channels/{channel_id}/typing", self._h, None)
        except Exception:
            pass

    def recent(self, channel_id: str, limit: int = 10) -> list[dict]:
        body = _check(*self._t("GET", f"{API}/channels/{channel_id}/messages?limit={max(1, min(limit, 50))}", self._h, None), "메시지 조회")
        out = []
        for m in body if isinstance(body, list) else []:
            author = (m.get("author") or {}).get("username", "?")
            out.append({"id": m.get("id"), "author": author, "content": m.get("content", ""), "timestamp": m.get("timestamp", "")})
        return out


class DiscordClient:
    """Whichever of webhook/bot is configured; announce() picks the right one."""

    def __init__(self, webhook_url: str = "", bot_token: str = "", channel_id: str = "", username: str = "ARIUS", transport: Transport | None = None) -> None:
        self.webhook = DiscordWebhook(webhook_url, username, transport) if webhook_url else None
        self.bot = DiscordBot(bot_token, transport) if bot_token else None
        self.channel_id = channel_id

    @property
    def can_announce(self) -> bool:
        return self.webhook is not None or (self.bot is not None and bool(self.channel_id))

    def announce(self, content: str) -> str:
        if self.webhook is not None:
            msg = self.webhook.send(content)
            return f"디스코드(웹훅) 전송 완료. 메시지 ID {msg.get('id', '?')}"
        if self.bot is not None and self.channel_id:
            msg = self.bot.send(self.channel_id, content)
            return f"디스코드(봇) 전송 완료. 메시지 ID {msg.get('id', '?')}"
        raise DiscordError("디스코드 설정이 없습니다. discord.webhook_url 또는 bot_token+channel_id 를 설정하십시오.")
