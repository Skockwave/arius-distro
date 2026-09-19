"""Tools the agent can call. Each declares a capability (RBAC) and a risk level
for the autonomy gate: "read" changes nothing, "write" changes server/Discord/
memory state, "danger" stops or restarts the server.

Deliberately absent: shell execution, file writing, file deletion. Files can
only be listed/read, and only inside the server folder or agent.read_paths.
"""

from __future__ import annotations

import json
import os
import threading
import time
import zipfile
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from arius import minecraft as mc
from arius import permissions as perm
from arius import sysinfo
from arius.config import AriusConfig
from arius.desktop import Desktop
from arius.discord import DiscordClient, DiscordError, format_announcement
from arius.memory import Memory
from arius.permissions import Session
from arius.privacy import looks_secret, refuse_secret_message

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
    desktop_factory: Callable | None = None
    sleeper: Callable[[float], None] = time.sleep
    background: bool = True  # long restarts run on a thread; tests set False
    _desktop: object = field(default=None, repr=False)

    def desktop(self) -> Desktop:
        if self._desktop is None:
            if self.desktop_factory is not None:
                self._desktop = self.desktop_factory()
            else:
                d = self.config.desktop
                self._desktop = Desktop(d.programs, d.sites, d.folders, allow_any_url=d.allow_any_url, protected=d.protected_processes)
        return self._desktop

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

    def rcon_needs_confirmation(self, command: str) -> bool:
        """Kick/ban/op/whitelist-remove and friends always ask, whatever the autonomy level."""
        words = command.strip().lstrip("/").lower().split()
        if not words:
            return False
        heads = {words[0]}
        if len(words) > 1:
            heads.add(f"{words[0]} {words[1]}")
        return bool(heads & {c.lower() for c in self.config.agent.rcon_confirm})

    def backup_dir(self) -> Path | None:
        m = self.config.minecraft
        if m.backup_dir:
            return Path(os.path.expanduser(m.backup_dir))
        sd = self.server_dir()
        return Path(sd) / "backups" if sd else None

    def latest_backup(self) -> Path | None:
        d = self.backup_dir()
        if not d or not d.is_dir():
            return None
        files = [p for p in d.iterdir() if p.is_file() and p.suffix.lower() == ".zip"]
        return max(files, key=lambda p: p.stat().st_mtime) if files else None


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
    impact: str = ""  # shown in "실행 예정 / 영향" confirmations
    # Optional per-call check: True = this particular call must be confirmed even if the
    # tool is auto-allowed (e.g. minecraft_command with "kick").
    confirm_if: Callable[[ToolContext, dict], bool] | None = None

    def spec(self) -> dict:
        return {"name": self.name, "description": self.description, "params": self.params, "risk": self.risk}

    def describe(self, args: dict) -> str:
        shown = {k: v for k, v in args.items() if v not in ("", None)}
        return f"{self.description} — {self.name} {json.dumps(shown, ensure_ascii=False)}" if shown else f"{self.description} — {self.name}"

    def impact_text(self) -> str:
        if self.impact:
            return self.impact
        return {"read": "읽기만 하며 아무것도 바꾸지 않습니다.", "write": "서버·디스코드·기억 상태가 바뀝니다.", "danger": "서비스가 잠시 중단될 수 있습니다."}.get(self.risk, "")


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


def restart_precheck(ctx: ToolContext) -> tuple[str, dict]:
    """What the rules require before a stop/restart: players, downtime, backup, notice."""
    host, port = ctx.mc_host()
    status = ctx.pinger(host, port)
    latest = ctx.latest_backup()
    age_h = (time.time() - latest.stat().st_mtime) / 3600 if latest else None
    backup_line = f"{latest.name} ({age_h:.1f}시간 전)" if latest else "없음 (백업 폴더에 zip 이 없습니다)"
    info = {"online": status.online, "players": status.players_online, "names": status.player_names, "backup": latest, "backup_age_h": age_h}
    text = (
        f"현재 접속자: {status.players_online}명" + (f" ({', '.join(status.player_names)})" if status.player_names else "") + "\n"
        f"예상 중단 시간: 약 2~3분 (예고 {ctx.config.minecraft.restart_notice_seconds // 60}분 포함)\n"
        f"최근 백업: {backup_line}\n"
        f"채팅 공지: {'필요 (접속자 있음)' if status.players_online else '접속자 없음 — 짧은 예고만'}"
    )
    return text, info


def t_mc_restart(ctx: ToolContext, args: dict) -> str:
    """예고 → (대기) → 중지 → 시작. Long notices run in the background so the caller
    (agent loop / REPL) is not blocked for five minutes."""
    m = ctx.config.minecraft
    host, port = ctx.mc_host()
    if not ctx.pinger(host, port).online:
        return "서버가 이미 꺼져 있습니다. " + t_mc_start(ctx, {"wait": args.get("wait", True)})
    pre, info = restart_precheck(ctx)
    notice = " ".join(_s(args, "warning", m.restart_notice).split())
    if "delay" in args and args.get("delay") not in (None, ""):
        delay = max(0, min(int(float(args.get("delay") or 0)), 900))
    else:
        delay = max(0, min(int(m.restart_notice_seconds), 900)) if info["players"] else 10
    try:
        with ctx.rcon() as r:
            r.command(f"say {notice}")
    except mc.RconError as exc:
        return str(exc)

    def _finish() -> str:
        ctx.sleeper(delay)
        stop_msg = t_mc_stop(ctx, {"warning": "지금 재시작합니다.", "delay": 2})
        if "중지 명령" not in stop_msg:
            ctx.notify(f"재시작 실패: {stop_msg}")
            return stop_msg
        deadline = time.monotonic() + 90
        while ctx.pinger(host, port).online and time.monotonic() < deadline:
            ctx.sleeper(3)
        out = t_mc_start(ctx, {"wait": args.get("wait", True)})
        ctx.memory.log_agent("action", "minecraft_restart 완료", out[:300])
        ctx.notify("완료했습니다. 서버 재시작: " + (out.splitlines() or [""])[-1])
        return out

    head = f"실행하겠습니다: {m.name} 재시작 (예고 후 {delay}초 뒤 중지 → 시작)\n{pre}\n공지 전송: \"{notice}\""
    if ctx.background and delay > 15:
        threading.Thread(target=_finish, name="arius-mc-restart", daemon=True).start()
        return head + "\n재시작은 예고 시간이 지나면 자동으로 이어지며, 끝나면 알려드립니다."
    return head + "\n" + _finish()


_PLAYER_FILES = {"whitelist": "whitelist.json", "ops": "ops.json", "bans": "banned-players.json", "ip_bans": "banned-ips.json"}
_PLAYER_LABELS = {"whitelist": "화이트리스트", "ops": "운영자(OP)", "bans": "밴 목록", "ip_bans": "IP 밴 목록"}


def t_mc_players(ctx: ToolContext, args: dict) -> str:
    """Read whitelist.json / ops.json / banned-players.json (no RCON needed)."""
    sd = ctx.server_dir()
    if not sd:
        return "서버 폴더를 찾지 못했습니다. config 의 minecraft.server_dir 를 설정하십시오."
    which = _s(args, "which", "all").strip().lower() or "all"
    keys = list(_PLAYER_FILES) if which == "all" else [k for k in _PLAYER_FILES if k == which or which in k]
    if not keys:
        return f"알 수 없는 목록: {which} (whitelist | ops | bans | ip_bans | all)"
    out = []
    for k in keys:
        p = Path(sd) / _PLAYER_FILES[k]
        if not p.exists():
            out.append(f"{_PLAYER_LABELS[k]}: 파일 없음 ({p.name})")
            continue
        try:
            rows = json.loads(p.read_text(encoding="utf-8", errors="replace") or "[]")
        except (OSError, json.JSONDecodeError) as exc:
            out.append(f"{_PLAYER_LABELS[k]}: 읽기 실패 ({exc})")
            continue
        names = []
        for r in rows if isinstance(rows, list) else []:
            if not isinstance(r, dict):
                continue
            n = r.get("name") or r.get("ip") or "?"
            extra = ""
            if k == "ops":
                extra = f" (레벨 {r.get('level', '?')})"
            elif k in ("bans", "ip_bans") and r.get("reason"):
                extra = f" — {r.get('reason')}"
            names.append(f"{n}{extra}")
        out.append(f"{_PLAYER_LABELS[k]} ({len(names)}명): " + (", ".join(names) if names else "(없음)"))
    return "\n".join(out)


def t_mc_backup(ctx: ToolContext, args: dict) -> str:
    """save-all (when RCON works), then zip the world folders into the backup dir. Never deletes old backups."""
    sd = ctx.server_dir()
    if not sd:
        return "서버 폴더를 찾지 못했습니다. config 의 minecraft.server_dir 를 설정하십시오."
    props = mc.read_properties(sd)
    level = props.get("level-name", "world") or "world"
    worlds = [Path(sd) / n for n in (level, f"{level}_nether", f"{level}_the_end") if (Path(sd) / n).is_dir()]
    if not worlds:
        return f"월드 폴더를 찾지 못했습니다 (level-name={level}, 폴더 {sd})."
    saved = ""
    try:
        with ctx.rcon() as r:
            r.command("save-all flush")
            saved = "save-all 완료. "
    except (Refused, mc.RconError) as exc:
        saved = f"(RCON 없이 진행 — {str(exc).split('.')[0][:60]}) "
    dest_dir = ctx.backup_dir() or (Path(sd) / "backups")
    try:
        dest_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        return f"백업 폴더를 만들 수 없습니다: {dest_dir} ({exc})"
    stamp = time.strftime("%Y%m%d-%H%M%S")
    dest = dest_dir / f"{level}-{stamp}.zip"
    files = 0
    try:
        with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as zf:
            for w in worlds:
                for f in w.rglob("*"):
                    if f.is_file() and f.name != "session.lock":
                        zf.write(f, f.relative_to(Path(sd)))
                        files += 1
    except OSError as exc:
        return f"백업 실패: {exc}"
    size_mb = dest.stat().st_size / 1e6
    ctx.memory.learn_fact(SYSTEM_USER, "mc.last_backup", f"{dest}|{time.time():.0f}", source="system")
    return f"완료했습니다. {saved}백업 생성: {dest} ({files}개 파일, {size_mb:.1f}MB)"


def t_mc_backup_status(ctx: ToolContext, args: dict) -> str:
    latest = ctx.latest_backup()
    d = ctx.backup_dir()
    if latest is None:
        return f"백업 없음 — {d or '백업 폴더 미설정'} 에 zip 백업이 없습니다. '서버 백업' 으로 만들 수 있습니다."
    age_h = (time.time() - latest.stat().st_mtime) / 3600
    limit = ctx.config.agent.alert_backup_hours
    flag = "🟢" if age_h <= limit else "🟡"
    return f"{flag} 최근 백업: {latest.name} — {age_h:.1f}시간 전, {latest.stat().st_size / 1e6:.1f}MB (폴더: {latest.parent})" +         ("" if age_h <= limit else f"\n주의: {limit}시간보다 오래됐습니다.")


# --- PC control ------------------------------------------------------------------------


def t_open_url(ctx: ToolContext, args: dict) -> str:
    return ctx.desktop().open_url(_s(args, "target"))


def t_open_path(ctx: ToolContext, args: dict) -> str:
    return ctx.desktop().open_path(_s(args, "target"))


def t_launch_program(ctx: ToolContext, args: dict) -> str:
    return ctx.desktop().launch(_s(args, "name"))


def t_list_processes(ctx: ToolContext, args: dict) -> str:
    return ctx.desktop().running(_i(args, "limit", 15))


def t_close_program(ctx: ToolContext, args: dict) -> str:
    return ctx.desktop().close(_s(args, "name"), bool(args.get("force", False)))


def t_switch_window(ctx: ToolContext, args: dict) -> str:
    return ctx.desktop().switch_window(_s(args, "title"))


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
    if looks_secret(f"{key} {value}"):
        return refuse_secret_message()
    ctx.memory.learn_fact(ctx.session.user.username, key, value, source="agent", confidence=0.8)
    return f"기억했습니다: {key} = {value} (출처: 에이전트, 신뢰도 80%)"


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
        Tool("minecraft_players", "화이트리스트 / 운영자(OP) / 밴 목록 조회 (서버 폴더의 json)", {"which": "whitelist|ops|bans|ip_bans|all"}, perm.CAP_MC_READ, "read", t_mc_players),
        Tool("minecraft_backup_status", "최근 월드 백업의 시각·크기 확인", {}, perm.CAP_MC_READ, "read", t_mc_backup_status),
        Tool("minecraft_command", "허용 목록 안의 콘솔 명령 (RCON): list, tps, save-all, whitelist add X, kick X ... (킥/밴/OP/화이트리스트 제거는 항상 확인)", {"command": "콘솔 명령"}, perm.CAP_MC_ADMIN, "write", t_mc_command,
             impact="콘솔 명령이 서버에 즉시 적용됩니다.", confirm_if=lambda ctx, a: ctx.rcon_needs_confirmation(_s(a, "command"))),
        Tool("minecraft_say", "서버 내 전체 채팅 공지", {"message": "내용"}, perm.CAP_MC_ADMIN, "write", t_mc_say, impact="모든 접속자에게 채팅이 표시됩니다."),
        Tool("minecraft_start", "꺼진 서버를 시작 (start.bat/start.sh 또는 start_command)", {"wait": "온라인까지 대기 여부", "timeout": "대기 초"}, perm.CAP_MC_ADMIN, "write", t_mc_start, impact="서버 프로세스가 새로 뜹니다."),
        Tool("minecraft_backup", "save-all 후 월드 폴더를 zip 으로 백업 (기존 백업은 지우지 않음)", {}, perm.CAP_MC_ADMIN, "write", t_mc_backup, impact="디스크에 백업 파일이 생깁니다(월드 크기만큼)."),
        Tool("minecraft_stop", "서버를 안전하게 중지 (RCON stop)", {"warning": "중지 전 채팅 예고", "delay": "예고 후 대기 초"}, perm.CAP_MC_ADMIN, "danger", t_mc_stop, impact="접속자가 모두 끊기고 서버가 꺼집니다."),
        Tool("minecraft_restart", "예고 → 중지 → 재시작 (접속자·백업 사전 점검 포함)", {"warning": "예고 문구", "delay": "예고 후 대기 초", "wait": "온라인까지 대기"}, perm.CAP_MC_ADMIN, "danger", t_mc_restart, impact="약 2~3분간 서버가 중단됩니다."),
        Tool("minecraft_enable_rcon", "server.properties 에 RCON 켜기 (백업 생성, 재시작 필요)", {"password": "RCON 암호"}, perm.CAP_MC_ADMIN, "write", t_mc_enable_rcon, impact="server.properties 가 수정됩니다(.bak 보관)."),
        Tool("discord_announce", "디스코드 채널에 공지 게시", {"title": "제목", "body": "본문", "footer": "꼬리말", "everyone": "true면 @everyone"}, perm.CAP_DISCORD_ANNOUNCE, "write", t_discord_announce),
        Tool("discord_recent", "디스코드 채널 최근 메시지 (봇 필요)", {"limit": "개수"}, perm.CAP_DISCORD_READ, "read", t_discord_recent),
        Tool("remember", "사실을 장기 기억에 저장 (비밀번호·키·토큰은 거부)", {"key": "항목", "value": "내용"}, perm.CAP_MEMORY_WRITE, "write", t_remember, impact="장기 기억에 항목이 추가됩니다."),
        Tool("recall", "장기 기억 검색", {"query": "검색어"}, perm.CAP_MEMORY_READ, "read", t_recall),
        Tool("notify_user", "사용자에게 메시지 표시 (행동 없이 알리기만)", {"message": "내용"}, perm.CAP_CHAT, "read", t_notify_user),
        Tool("open_url", "웹사이트 열기 (등록된 사이트 이름 또는 URL)", {"target": "사이트 이름 또는 URL"}, perm.CAP_DESKTOP_OPEN, "write", t_open_url, impact="기본 브라우저에 탭이 열립니다."),
        Tool("open_path", "파일/폴더 열기 (다운로드, 문서, 바탕화면 또는 경로)", {"target": "폴더 이름 또는 경로"}, perm.CAP_DESKTOP_OPEN, "write", t_open_path, impact="탐색기/연결 프로그램이 열립니다."),
        Tool("launch_program", "등록된 프로그램 실행 (메모장, 크롬, config desktop.programs …)", {"name": "프로그램 이름"}, perm.CAP_DESKTOP_OPEN, "write", t_launch_program, impact="프로그램이 실행됩니다."),
        Tool("switch_window", "창 전환 (제목 앞부분)", {"title": "창 제목"}, perm.CAP_DESKTOP_OPEN, "write", t_switch_window, impact="해당 창이 앞으로 옵니다."),
        Tool("list_processes", "실행 중인 프로그램과 메모리 사용량", {"limit": "개수"}, perm.CAP_SYSTEM_INFO, "read", t_list_processes),
        Tool("close_program", "프로그램 종료 (보호 프로세스 제외, 항상 확인)", {"name": "실행 파일명", "force": "true=강제"}, perm.CAP_DESKTOP_MANAGE, "danger", t_close_program, impact="저장하지 않은 작업이 사라질 수 있습니다."),
    ]
    return {t.name: t for t in tools}


def tools_prompt(tools: dict[str, Tool], session: Session) -> str:
    usable = [t.spec() for t in tools.values() if session.can(t.capability)]
    return json.dumps(usable, ensure_ascii=False)
