"""Minecraft server helpers — Server List Ping and RCON, standard library only.

* ``ping_server``  — the status handshake every launcher uses: online/offline,
  player count, version, MOTD. Works against any Java server, no credentials.
* ``Rcon``         — Source-RCON console access (``enable-rcon=true`` +
  ``rcon.password`` in server.properties). Lets ARIUS run ``list``,
  ``say``, ``whitelist add``, ``save-all``, ``stop`` ... remotely.
* ``load_distribution`` — reads the Helios ``distribution.json`` manifest that
  lives at the root of this repository, so ARIUS knows the server address,
  Minecraft/Forge version and mod list without extra configuration.

SRV records are not resolved (no DNS SRV in the standard library); if your
host uses one, put the real port in ``minecraft.port``.
"""

from __future__ import annotations

import json
import os as _os
import re as _re
import socket
import struct
import subprocess as _sp
import sys as _sys
import time as _time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

DEFAULT_PORT = 25565
DEFAULT_RCON_PORT = 25575
_PROTOCOL_1_20_1 = 763


# --- VarInt / packet helpers -------------------------------------------------


def write_varint(value: int) -> bytes:
    value &= 0xFFFFFFFF
    out = bytearray()
    while True:
        byte = value & 0x7F
        value >>= 7
        if value:
            out.append(byte | 0x80)
        else:
            out.append(byte)
            return bytes(out)


def read_varint(read: Callable[[int], bytes]) -> int:
    """Read a VarInt using ``read(n)`` which must return exactly n bytes."""
    num = 0
    for i in range(5):
        chunk = read(1)
        if not chunk:
            raise ConnectionError("connection closed while reading VarInt")
        byte = chunk[0]
        num |= (byte & 0x7F) << (7 * i)
        if not byte & 0x80:
            break
    else:
        raise ValueError("VarInt too long")
    if num & (1 << 31):
        num -= 1 << 32
    return num


def _pack_string(s: str) -> bytes:
    data = s.encode("utf-8")
    return write_varint(len(data)) + data


def _frame(packet_id: int, payload: bytes) -> bytes:
    body = write_varint(packet_id) + payload
    return write_varint(len(body)) + body


def _recv_exact(sock: socket.socket, n: int) -> bytes:
    buf = bytearray()
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise ConnectionError("connection closed")
        buf.extend(chunk)
    return bytes(buf)


def flatten_chat(component) -> str:
    """Turn a chat component (string / dict / list) into plain text."""
    if component is None:
        return ""
    if isinstance(component, str):
        return component
    if isinstance(component, list):
        return "".join(flatten_chat(c) for c in component)
    if isinstance(component, dict):
        text = str(component.get("text", ""))
        extra = component.get("extra") or []
        return text + "".join(flatten_chat(c) for c in extra)
    return str(component)


# --- Server List Ping ----------------------------------------------------------


@dataclass
class ServerStatus:
    host: str
    port: int
    online: bool
    players_online: int = 0
    players_max: int = 0
    player_names: list[str] = field(default_factory=list)
    version: str = ""
    motd: str = ""
    latency_ms: float = 0.0
    error: str = ""

    def summary(self) -> str:
        if not self.online:
            return f"🔴 서버 오프라인 ({self.host}:{self.port}) — {self.error or '응답 없음'}"
        names = f" — {', '.join(self.player_names)}" if self.player_names else ""
        motd = f'\n  MOTD: "{self.motd}"' if self.motd else ""
        return (
            f"🟢 서버 온라인 ({self.host}:{self.port})\n"
            f"  접속자: {self.players_online}/{self.players_max}{names}\n"
            f"  버전: {self.version or '?'}  응답: {self.latency_ms:.0f}ms{motd}"
        )


def parse_host(address: str, default_port: int = DEFAULT_PORT) -> tuple[str, int]:
    address = (address or "").strip()
    if ":" in address and not address.startswith("["):
        host, _, port = address.rpartition(":")
        try:
            return host, int(port)
        except ValueError:
            pass
    return address, default_port


def ping_server(host: str, port: int = DEFAULT_PORT, timeout: float = 5.0) -> ServerStatus:
    import time

    started = time.monotonic()
    try:
        with socket.create_connection((host, port), timeout=timeout) as sock:
            sock.settimeout(timeout)
            handshake = (
                write_varint(_PROTOCOL_1_20_1)
                + _pack_string(host)
                + struct.pack(">H", port)
                + write_varint(1)
            )
            sock.sendall(_frame(0x00, handshake))
            sock.sendall(_frame(0x00, b""))  # status request

            read = lambda n: _recv_exact(sock, n)  # noqa: E731
            _length = read_varint(read)
            packet_id = read_varint(read)
            if packet_id != 0x00:
                raise ValueError(f"unexpected packet id {packet_id}")
            json_len = read_varint(read)
            payload = json.loads(read(json_len).decode("utf-8", errors="replace"))
    except (OSError, ValueError, ConnectionError, json.JSONDecodeError) as exc:
        return ServerStatus(host=host, port=port, online=False, error=f"{exc.__class__.__name__}: {exc}")

    latency = (time.monotonic() - started) * 1000
    players = payload.get("players") or {}
    version = payload.get("version") or {}
    sample = players.get("sample") or []
    return ServerStatus(
        host=host,
        port=port,
        online=True,
        players_online=int(players.get("online", 0) or 0),
        players_max=int(players.get("max", 0) or 0),
        player_names=[str(p.get("name", "")) for p in sample if isinstance(p, dict)],
        version=str(version.get("name", "")),
        motd=" ".join(flatten_chat(payload.get("description")).split()),
        latency_ms=latency,
    )


# --- RCON -----------------------------------------------------------------------

_RCON_LOGIN = 3
_RCON_COMMAND = 2
_RCON_RESPONSE = 0


class RconError(Exception):
    pass


class RconAuthError(RconError):
    pass


class Rcon:
    """Minimal Source-RCON client. Use as a context manager."""

    def __init__(self, host: str, port: int = DEFAULT_RCON_PORT, password: str = "", timeout: float = 5.0) -> None:
        self.host = host
        self.port = port
        self.password = password
        self.timeout = timeout
        self._sock: socket.socket | None = None
        self._next_id = 1

    def __enter__(self) -> "Rcon":
        self.connect()
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def connect(self) -> None:
        try:
            self._sock = socket.create_connection((self.host, self.port), timeout=self.timeout)
        except OSError as exc:
            raise RconError(f"RCON 연결 실패 ({self.host}:{self.port}): {exc}") from exc
        self._sock.settimeout(self.timeout)
        req_id, kind, _ = self._roundtrip(_RCON_LOGIN, self.password)
        if req_id == -1:
            self.close()
            raise RconAuthError("RCON 암호가 틀렸습니다.")

    def close(self) -> None:
        if self._sock is not None:
            try:
                self._sock.close()
            finally:
                self._sock = None

    def command(self, cmd: str) -> str:
        if self._sock is None:
            raise RconError("RCON 연결이 없습니다.")
        _, _, body = self._roundtrip(_RCON_COMMAND, cmd)
        return body

    # -- wire format
    def _send(self, kind: int, body: str) -> int:
        assert self._sock is not None
        req_id = self._next_id
        self._next_id += 1
        data = body.encode("utf-8")
        packet = struct.pack("<ii", req_id, kind) + data + b"\x00\x00"
        self._sock.sendall(struct.pack("<i", len(packet)) + packet)
        return req_id

    def _recv(self) -> tuple[int, int, str]:
        assert self._sock is not None
        (length,) = struct.unpack("<i", _recv_exact(self._sock, 4))
        if length < 10 or length > 1 << 20:
            raise RconError(f"잘못된 RCON 패킷 길이: {length}")
        raw = _recv_exact(self._sock, length)
        req_id, kind = struct.unpack("<ii", raw[:8])
        body = raw[8:-2].decode("utf-8", errors="replace")
        return req_id, kind, body

    def _roundtrip(self, kind: int, body: str) -> tuple[int, int, str]:
        try:
            self._send(kind, body)
            return self._recv()
        except (OSError, ConnectionError, struct.error) as exc:
            raise RconError(f"RCON 통신 오류: {exc}") from exc


# --- Distribution manifest -------------------------------------------------------


@dataclass
class DistributionInfo:
    path: str
    servers: list[dict]

    @property
    def main(self) -> dict | None:
        for s in self.servers:
            if s.get("mainServer"):
                return s
        return self.servers[0] if self.servers else None

    def summary(self) -> str:
        if not self.servers:
            return "배포 매니페스트에 서버가 없습니다."
        lines = [f"배포 매니페스트: {self.path}"]
        for s in self.servers:
            mods = _count_modules(s.get("modules") or [])
            flag = " (메인)" if s.get("mainServer") else ""
            lines.append(
                f"  • {s.get('name', s.get('id', '?'))}{flag}\n"
                f"    주소: {s.get('address', '?')}  MC {s.get('minecraftVersion', '?')}  배포 v{s.get('version', '?')}\n"
                f"    모듈: {mods}개  설명: {s.get('description', '')}"
            )
        return "\n".join(lines)


def _count_modules(modules: list[dict]) -> int:
    n = 0
    for m in modules:
        n += 1
        n += _count_modules(m.get("subModules") or [])
    return n


def load_distribution(path: str | Path) -> DistributionInfo | None:
    p = Path(path).expanduser()
    if not p.exists():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return DistributionInfo(path=str(p), servers=list(data.get("servers") or []))


# --- Local Bukkit/Spigot/Paper server management ----------------------------------

_SERVER_JAR_HINTS = ("paper", "spigot", "bukkit", "craftbukkit", "purpur", "folia", "server.jar", "forge", "fabric", "minecraft_server")


@dataclass
class ServerProcess:
    pid: int
    command: str
    memory_mb: float = 0.0
    cwd: str = ""

    def summary(self) -> str:
        mem = f"  메모리: {self.memory_mb:.0f}MB" if self.memory_mb else ""
        cwd = f"\n  폴더: {self.cwd}" if self.cwd else ""
        cmd = self.command if len(self.command) <= 120 else self.command[:119] + "…"
        return f"PID {self.pid}{mem}\n  명령: {cmd}{cwd}"


def _looks_like_server(cmdline: str) -> bool:
    """A JVM launched with -jar on a server jar — not just any command mentioning 'paper'."""
    parts = cmdline.strip().split()
    if not parts:
        return False
    exe = _os.path.basename(parts[0].strip('"').strip("'")).lower()
    if not exe.startswith("java"):
        return False
    low = cmdline.lower()
    return "-jar" in low and any(h in low for h in _SERVER_JAR_HINTS)


def find_server_processes(run=None) -> list[ServerProcess]:
    """Best-effort discovery of running Minecraft server JVMs on this machine."""
    run = run or (lambda args, **kw: _sp.run(args, capture_output=True, text=True, errors="replace", timeout=15, **kw))
    found: list[ServerProcess] = []
    try:
        if _sys.platform == "win32":
            ps = (
                "Get-CimInstance Win32_Process | Where-Object { $_.Name -like 'java*' } | "
                "ForEach-Object { '{0}|{1}|{2}' -f $_.ProcessId, [math]::Round($_.WorkingSetSize/1MB), $_.CommandLine }"
            )
            out = run(["powershell", "-NoProfile", "-Command", ps]).stdout
            for line in out.splitlines():
                parts = line.split("|", 2)
                if len(parts) == 3 and _looks_like_server(parts[2]):
                    found.append(ServerProcess(int(parts[0]), parts[2].strip(), float(parts[1] or 0), _guess_cwd(parts[2])))
        else:
            out = run(["ps", "-eo", "pid=,rss=,args="]).stdout
            for line in out.splitlines():
                bits = line.strip().split(None, 2)
                if len(bits) == 3 and _looks_like_server(bits[2]):
                    pid = int(bits[0])
                    cwd = ""
                    try:
                        cwd = _os.readlink(f"/proc/{pid}/cwd")
                    except OSError:
                        cwd = _guess_cwd(bits[2])
                    found.append(ServerProcess(pid, bits[2], float(bits[1]) / 1024.0, cwd))
    except (OSError, ValueError, _sp.SubprocessError):
        pass
    return found


def _guess_cwd(cmdline: str) -> str:
    m = _re.search(r"-jar\s+\"?([^\s\"]+\.jar)", cmdline, _re.IGNORECASE)
    if m and _os.path.isabs(m.group(1)):
        return _os.path.dirname(m.group(1))
    return ""


def detect_server_dir(configured: str = "", processes: list[ServerProcess] | None = None) -> str:
    """The server folder: config wins; else the running JVM's folder; else ''."""
    if configured:
        return str(Path(configured).expanduser())
    for proc in processes if processes is not None else find_server_processes():
        if proc.cwd and Path(proc.cwd, "server.properties").exists():
            return proc.cwd
    for candidate in (Path.cwd(), Path.home() / "server", Path.home() / "minecraft"):
        if (candidate / "server.properties").exists():
            return str(candidate)
    return ""


def tail_log(server_dir: str, lines: int = 40, pattern: str = "") -> str:
    """Last lines of logs/latest.log, optionally only those matching a regex."""
    log = Path(server_dir) / "logs" / "latest.log"
    if not log.exists():
        return f"로그 파일이 없습니다: {log}"
    try:
        text = log.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError as exc:
        return f"로그를 읽을 수 없습니다: {exc}"
    if pattern:
        try:
            rx = _re.compile(pattern, _re.IGNORECASE)
        except _re.error as exc:
            return f"잘못된 패턴: {exc}"
        text = [ln for ln in text if rx.search(ln)]
    tail = text[-max(1, lines):]
    return "\n".join(tail) if tail else "(해당 줄 없음)"


def read_properties(server_dir: str) -> dict[str, str]:
    p = Path(server_dir) / "server.properties"
    props: dict[str, str] = {}
    if not p.exists():
        return props
    for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            k, _, v = line.partition("=")
            props[k.strip()] = v.strip()
    return props


def enable_rcon(server_dir: str, password: str, port: int = DEFAULT_RCON_PORT) -> str:
    """Turn on RCON in server.properties (keeps a .bak). Server restart required."""
    p = Path(server_dir) / "server.properties"
    if not p.exists():
        return f"server.properties 가 없습니다: {p}"
    if not password:
        return "RCON 암호가 비어 있습니다."
    original = p.read_text(encoding="utf-8", errors="replace")
    wanted = {"enable-rcon": "true", "rcon.port": str(port), "rcon.password": password}
    seen: set[str] = set()
    out: list[str] = []
    for line in original.splitlines():
        key = line.partition("=")[0].strip() if "=" in line and not line.lstrip().startswith("#") else None
        if key in wanted:
            out.append(f"{key}={wanted[key]}")
            seen.add(key)
        else:
            out.append(line)
    for key, val in wanted.items():
        if key not in seen:
            out.append(f"{key}={val}")
    p.with_suffix(".properties.bak").write_text(original, encoding="utf-8")
    p.write_text("\n".join(out) + "\n", encoding="utf-8")
    return f"RCON 설정 완료 (포트 {port}). 백업: {p.with_suffix('.properties.bak').name}. 서버를 재시작해야 적용됩니다."


def start_server(server_dir: str, command: str = "") -> str:
    """Launch the server detached. Uses start_command, else start.bat/start.sh/run.sh, else java -jar."""
    d = Path(server_dir)
    if not d.exists():
        return f"서버 폴더가 없습니다: {d}"
    cmd = command.strip()
    if not cmd:
        for name in ("start.bat", "start.sh", "run.bat", "run.sh", "start.command"):
            if (d / name).exists():
                cmd = f'"{d / name}"' if _sys.platform == "win32" else f'bash "{d / name}"'
                break
    if not cmd:
        jars = sorted(j for j in d.glob("*.jar") if any(h in j.name.lower() for h in _SERVER_JAR_HINTS))
        if not jars:
            return "시작 스크립트(start.bat/start.sh)나 서버 jar를 찾지 못했습니다. minecraft.start_command 를 설정하십시오."
        cmd = f'java -Xmx4G -jar "{jars[0].name}" nogui'
    try:
        if _sys.platform == "win32":
            _sp.Popen(cmd, cwd=str(d), shell=True, creationflags=getattr(_sp, "CREATE_NEW_CONSOLE", 0))
        else:
            _sp.Popen(cmd, cwd=str(d), shell=True, stdout=_sp.DEVNULL, stderr=_sp.DEVNULL, stdin=_sp.DEVNULL, start_new_session=True)
    except OSError as exc:
        return f"서버 시작 실패: {exc}"
    return f"서버 시작 명령을 실행했습니다: {cmd}  (폴더: {d})"


def wait_for_online(host: str, port: int, timeout: float = 120.0, interval: float = 5.0) -> ServerStatus:
    deadline = _time.monotonic() + timeout
    status = ping_server(host, port, timeout=3.0)
    while not status.online and _time.monotonic() < deadline:
        _time.sleep(interval)
        status = ping_server(host, port, timeout=3.0)
    return status
