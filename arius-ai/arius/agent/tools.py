"""Tools the agent can call. Each declares a capability (RBAC) and a risk level
for the autonomy gate: "read" changes nothing, "write" changes server/Discord/
memory state, "danger" stops or restarts the server.

Deliberately absent: shell execution, file writing, file deletion. Files can
only be listed/read, and only inside the server folder or agent.read_paths.
"""

from __future__ import annotations

import json
import os
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from arius import minecraft as mc
from arius import permissions as perm
from arius import sysinfo
from arius.config import AriusConfig
from arius.discord import DiscordClient, DiscordError, format_announcement
from arius.memory import Memory
from arius.permissions import Session

SYSTEM_USER = "__arius__"
_MAX_OBS = 3500


class Refused(Exception):
    """The tool refused the request (outside read paths, command not allowlisted...)."""


@dataclass
class ToolContext:
    config: AriusConfig
    memory: Memory
    session: Session
    notify: Callable[[str], None] = print
    # injectable seams (tests swap these for fakes)
    pinger: Callable = mc.ping_server
    rcon_factory: Callable = lambda host, port, pw: mc.Rcon(host, port, pw)
    discord_factory: Callable | None = None
    process_finder: Callable = mc.find_server_processes
    server_starter: Callable = mc.start_server
    snapshot_fn: Callable = sysinfo.snapshot

    def discord(self) -> DiscordClient:
        if self.discord_factory is not None:
            return self.discord_factory()
        d = self.config.discord
        return DiscordClient(d.resolved_webhook, d.resolved_token, d.channel_id, d.username)

    def server_dir(self) -> str:
        return mc.detect_server_dir(self.config.minecraft.server_dir, self.process_finder())

    def mc_host(self) -> tuple[str, int]:
        m = self.config.minecraft
        host, port = mc.parse_host(m.host or "localhost", m.port)
        return host or "localhost", port

    def rcon(self):
        m = self.config.minecraft
        host = m.rcon_host or self.mc_host()[0]
        pw = m.resolved_rcon_password
        if not pw:
            raise Refused(
                "RCON 암호가 설정되지 않았습니다. 'minecraft_enable_rcon' 도구로 server.properties 에 켜고, "
                "config 의 minecraft.rcon_password (또는 환경변수 ARIUS_RCON_PASSWORD) 에 같은 암호를 넣으십시오."
            )
        return self.rcon_factory(host, m.rcon_port, pw)

    def read_roots(self) -> list[Path]:
        roots = [Path(os.path.expanduser(p)).resolve() for p in self.config.agent.read_paths if p]
        sd = self.server_dir()
        if sd:
            roots.append(Path(sd).resolve())
        return roots

    def resolve_read_path(self, raw: str) -> Path:
        if not raw:
            raise Refused("경로가 비어 있습니다.")
        p = Path(os.path.expanduser(raw)).resolve()
        for root in self.read_roots():
            if os.path.normcase(str(p)) == os.path.normcase(str(root)) or _is_under(p, root):
                return p
        raise Refused(f"읽기 허용 폴더 밖입니다: {p} (서버 폴더 또는 agent.read_paths 만 읽을 수 있습니다)")

    def check_rcon_allowed(self, command: str) -> None:
        first = command.strip().lstrip("/").split()[0].lower() if command.strip() else ""
        if first not in {c.lower() for c in self.config.agent.rcon_allow}:
            raise Refused(f"허용되지 않은 콘솔 명령입니다: '{first}'. 허용 목록: {', '.join(self.config.agent.rcon_allow)}")


def _is_under(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


@dataclass
class Tool:
    name: str
    description: str
    params: dict[str, str]
    capability: str
    risk: str  # "read" | "write" | "danger"
    handler: Callable[[ToolContext, dict], str]

    def spec(self) -> dict:
        return {"name": self.name, "description": self.description, "params": self.params, "risk": self.risk}


def _s(args: dict, key: str, default: str = "") -> str:
    v = args.get(key, default)
    return "" if v is None else str(v)


def _i(args: dict, key: str, default: int) -> int:
    try:
        return int(args.get(key, default))
    except (TypeError, ValueError):
        return default


def _clip(text, limit: int = _MAX_OBS) -> str:
    text = text if isinstance(text, str) else str(text)
    return text if len(text) <= limit else text[:limit] + f"\n…(총 {len(text)}자 중 앞부분만)"


# --- observe: system & files (read only) ------------------------------------------


def t_system_status(ctx: ToolContext, args: dict) -> str:
    return sysinfo.describe(ctx.snapshot_fn())


def t_list_dir(ctx: ToolContext, args: dict) -> str:
    p = ctx.resolve_read_path(_s(args, "path") or ctx.server_dir())
    if not p.is_dir():
        return f"폴더가 아닙니다: {p}"
    limit = _i(args, "limit", 60)
    rows = []
    try:
        for entry in sorted(p.iterdir(), key=lambda e: e.name.lower()):
            try:
                size = entry.stat().st_size if entry.is_file() else 0
            except OSError:
                size = 0
            rows.append(f"{'📁' if entry.is_dir() else '📄'} {entry.name}" + (f"  ({size/1e6:.1f}MB)" if size >= 1e6 else ""))
    except OSError as exc:
        return f"읽기 실패: {exc}"
    more = f"\n…외 {len(rows) - limit}개" if len(rows) > limit else ""
    return f"{p} ({len(rows)}개)\n" + "\n".join(rows[:limit]) + more


def t_read_file(ctx: ToolContext, args: dict) -> str:
    p = ctx.resolve_read_path(_s(args, "path"))
    if not p.is_file():
        return f"파일이 아닙니다: {p}"
    try:
        return _clip(p.read_text(encoding="utf-8", errors="replace"), _i(args, "max_chars", 4000))
    except OSError as exc:
        return f"읽기 실패: {exc}"


# --- Minecraft (local Bukkit/Spigot/Paper) --------------------------------------------


def t_mc_status(ctx: ToolContext, args: dict) -> str:
    host, port = ctx.mc_host()
    status = ctx.pinger(host, port)
    procs = ctx.process_finder()
    lines = [f"[{ctx.config.minecraft.name}] " + status.summary()]
    if procs:
        lines.append("서버 프로세스: " + "; ".join(f"PID {p.pid} ({p.memory_mb:.0f}MB)" for p in procs))
    else:
        lines.append("서버 프로세스: 이 컴퓨터에서 실행 중인 서버 JVM을 찾지 못했습니다.")
    sd = ctx.server_dir()
    lines.append(f"서버 폴더: {sd or '(미확인 — config minecraft.server_dir 설정 권장)'}")
    return "\n".join(lines)


def t_mc_log(ctx: ToolContext, args: dict) -> str:
    sd = ctx.server_dir()
    if not sd:
        return "서버 폴더를 찾지 못했습니다. config 의 minecraft.server_dir 를 설정하십시오."
    return _clip(mc.tail_log(sd, _i(args, "lines", 40), _s(args, "pattern")))


def t_mc_command(ctx: ToolContext, args: dict) -> str:
    cmd = _s(args, "command").strip().lstrip("/")
    if not cmd:
        return "명령이 비어 있습니다."
    ctx.check_rcon_allowed(cmd)
    try:
        with ctx.rcon() as r:
            out = r.command(cmd)
    except mc.RconError as exc:
        return str(exc)
    return _clip(out or "(출력 없음)")


def t_mc_say(ctx: ToolContext, args: dict) -> str:
    msg = " ".join(_s(args, "message").split())
    if not msg:
        return "메시지가 비어 있습니다."
    try:
        with ctx.rcon() as r:
            r.command(f"say {msg}")
    except mc.RconError as exc:
        return str(exc)
    return f"서버 채팅에 공지했습니다: {msg}"


def t_mc_start(ctx: ToolContext, args: dict) -> str:
    host, port = ctx.mc_host()
    if ctx.pinger(host, port).online:
        return "서버가 이미 온라인입니다."
    sd = ctx.server_dir()
    if not sd:
        return "서버 폴더를 모릅니다. config 의 minecraft.server_dir 를 설정하십시오."
    result = ctx.server_starter(sd, ctx.config.minecraft.start_command)
    if bool(args.get("wait", True)) and "실행했습니다" in result:
        timeout = float(args.get("timeout", 120) or 120)
        deadline = time.monotonic() + timeout
        status = ctx.pinger(host, port)
        while not status.online and time.monotonic() < deadline:
            time.sleep(5)
            status = ctx.pinger(host, port)
        result += "\n" + ("🟢 서버가 온라인이 되었습니다." if status.online else "⏳ 아직 응답이 없습니다. 잠시 후 상태를 다시 확인하십시오.")
    return result


def t_mc_stop(ctx: ToolContext, args: dict) -> str:
    try:
        with ctx.rcon() as r:
            warn = " ".join(_s(args, "warning").split())
            if warn:
                r.command(f"say {warn}")
                time.sleep(min(float(args.get("delay", 0) or 0), 60))
            out = r.command("stop")
    except mc.RconError as exc:
        return str(exc)
    return f"서버에 중지 명령을 보냈습니다. {out}".strip()


def t_mc_restart(ctx: ToolContext, args: dict) -> str:
    stop_msg = t_mc_stop(ctx, {"warning": _s(args, "warning", "서버가 잠시 후 재시작됩니다."), "delay": args.get("delay", 10)})
    if "중지 명령" not in stop_msg:
        return stop_msg
    host, port = ctx.mc_host()
    deadline = time.monotonic() + 90
    while ctx.pinger(host, port).online and time.monotonic() < deadline:
        time.sleep(3)
    return stop_msg + "\n" + t_mc_start(ctx, {"wait": args.get("wait", True)})


def t_mc_enable_rcon(ctx: ToolContext, args: dict) -> str:
    sd = ctx.server_dir()
    if not sd:
        return "서버 폴더를 모릅니다. config 의 minecraft.server_dir 를 설정하십시오."
    pw = _s(args, "password").strip() or ctx.config.minecraft.resolved_rcon_password
    if not pw:
        return "RCON 암호를 인자로 주십시오 (password)."
    return mc.enable_rcon(sd, pw, ctx.config.minecraft.rcon_port)


# --- Discord ---------------------------------------------------------------------------


def t_discord_announce(ctx: ToolContext, args: dict) -> str:
    text = format_announcement(_s(args, "title"), _s(args, "body"), _s(args, "footer", ctx.config.minecraft.name), bool(args.get("everyone", False)))
    if not text.strip():
        return "공지 내용이 비어 있습니다."
    try:
        return ctx.discord().announce(text)
    except DiscordError as exc:
        return str(exc)


def t_discord_recent(ctx: ToolContext, args: dict) -> str:
    client = ctx.discord()
    if client.bot is None or not client.channel_id:
        return "최근 메시지 조회는 봇 토큰 + channel_id 설정이 필요합니다."
    try:
        msgs = client.bot.recent(client.channel_id, _i(args, "limit", 10))
    except DiscordError as exc:
        return str(exc)
    return "\n".join(f"[{m['timestamp'][:16]}] {m['author']}: {m['content']}" for m in msgs) or "(메시지 없음)"


# --- memory & user ----------------------------------------------------------------------


def t_remember(ctx: ToolContext, args: dict) -> str:
    key, value = _s(args, "key").strip(), _s(args, "value").strip()
    if not key or not value:
        return "key 와 value 가 필요합니다."
    ctx.memory.learn_fact(ctx.session.user.username, key, value)
    return f"기억했습니다: {key} = {value}"


def t_recall(ctx: ToolContext, args: dict) -> str:
    hits = ctx.memory.recall_facts(ctx.session.user.username, _s(args, "query"))
    return "\n".join(f"{f.key}: {f.value}" for f in hits) or "관련 기억이 없습니다."


def t_notify_user(ctx: ToolContext, args: dict) -> str:
    msg = _s(args, "message").strip()
    if msg:
        ctx.notify(msg)
    return "사용자에게 알렸습니다."


# --- registry ------------------------------------------------------------------------------


def build_registry() -> dict[str, Tool]:
    tools = [
        Tool("system_status", "CPU/메모리/디스크/상위 프로세스 등 이 컴퓨터의 현재 상태", {}, perm.CAP_SYSTEM_INFO, "read", t_system_status),
        Tool("list_dir", "서버 폴더(또는 허용 폴더) 내용 나열", {"path": "폴더 경로", "limit": "최대 항목 수"}, perm.CAP_FILES_READ, "read", t_list_dir),
        Tool("read_file", "서버 폴더(또는 허용 폴더)의 텍스트 파일 읽기", {"path": "파일 경로", "max_chars": "최대 글자 수"}, perm.CAP_FILES_READ, "read", t_read_file),
        Tool("minecraft_status", "서버 온라인/접속자/버전 + 로컬 프로세스", {}, perm.CAP_MC_READ, "read", t_mc_status),
        Tool("minecraft_log", "서버 latest.log 끝부분 (패턴 필터 가능: WARN|ERROR|joined)", {"lines": "줄 수", "pattern": "정규식"}, perm.CAP_MC_READ, "read", t_mc_log),
        Tool("minecraft_command", "허용 목록 안의 콘솔 명령 (RCON): list, tps, save-all, whitelist add X, kick X ...", {"command": "콘솔 명령"}, perm.CAP_MC_ADMIN, "write", t_mc_command),
        Tool("minecraft_say", "서버 내 전체 채팅 공지", {"message": "내용"}, perm.CAP_MC_ADMIN, "write", t_mc_say),
        Tool("minecraft_start", "꺼진 서버를 시작 (start.bat/start.sh 또는 start_command)", {"wait": "온라인까지 대기 여부", "timeout": "대기 초"}, perm.CAP_MC_ADMIN, "write", t_mc_start),
        Tool("minecraft_stop", "서버를 안전하게 중지 (RCON stop)", {"warning": "중지 전 채팅 예고", "delay": "예고 후 대기 초"}, perm.CAP_MC_ADMIN, "danger", t_mc_stop),
        Tool("minecraft_restart", "예고 → 중지 → 재시작", {"warning": "예고 문구", "delay": "예고 후 대기 초", "wait": "온라인까지 대기"}, perm.CAP_MC_ADMIN, "danger", t_mc_restart),
        Tool("minecraft_enable_rcon", "server.properties 에 RCON 켜기 (백업 생성, 재시작 필요)", {"password": "RCON 암호"}, perm.CAP_MC_ADMIN, "write", t_mc_enable_rcon),
        Tool("discord_announce", "디스코드 채널에 공지 게시", {"title": "제목", "body": "본문", "footer": "꼬리말", "everyone": "true면 @everyone"}, perm.CAP_DISCORD_ANNOUNCE, "write", t_discord_announce),
        Tool("discord_recent", "디스코드 채널 최근 메시지 (봇 필요)", {"limit": "개수"}, perm.CAP_DISCORD_READ, "read", t_discord_recent),
        Tool("remember", "사실을 장기 기억에 저장", {"key": "항목", "value": "내용"}, perm.CAP_MEMORY_WRITE, "write", t_remember),
        Tool("recall", "장기 기억 검색", {"query": "검색어"}, perm.CAP_MEMORY_READ, "read", t_recall),
        Tool("notify_user", "사용자에게 메시지 표시 (행동 없이 알리기만)", {"message": "내용"}, perm.CAP_CHAT, "read", t_notify_user),
    ]
    return {t.name: t for t in tools}


def tools_prompt(tools: dict[str, Tool], session: Session) -> str:
    usable = [t.spec() for t in tools.values() if session.can(t.capability)]
    return json.dumps(usable, ensure_ascii=False)
