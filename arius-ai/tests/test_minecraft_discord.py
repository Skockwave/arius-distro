"""Minecraft ping/RCON against fake local servers; Discord client with a fake transport;
Discord chat loop; wake-word voice conversation."""

import json
import socketserver
import struct
import threading

from arius.discord import DiscordBot, DiscordClient, DiscordError, format_announcement
from arius.discord_chat import DiscordChat
from arius.minecraft import (
    Rcon,
    RconAuthError,
    _frame,
    _pack_string,
    flatten_chat,
    parse_host,
    ping_server,
    read_varint,
    write_varint,
)
from arius.voice import SpeechToText, VoiceConversation


# --- Server List Ping ---------------------------------------------------------------

class _PingHandler(socketserver.BaseRequestHandler):
    def handle(self):
        rd = lambda n: self.request.recv(n)  # noqa: E731
        for _ in range(2):
            ln = read_varint(rd)
            self.request.recv(ln)
        status = {"version": {"name": "Paper 1.20.1", "protocol": 763},
                  "players": {"max": 20, "online": 2, "sample": [{"name": "steve", "id": "x"}]},
                  "description": {"text": "메테노 ", "extra": [{"text": "서버"}]}}
        self.request.sendall(_frame(0x00, _pack_string(json.dumps(status))))


def _serve(handler):
    srv = socketserver.TCPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, srv.server_address[1]


def test_varint_roundtrip():
    for v in (0, 1, 127, 128, 300, 763, 2**31 - 1, -1):
        data = write_varint(v)
        pos = 0

        def rd(n):
            nonlocal pos
            out = data[pos:pos + n]
            pos += n
            return out
        assert read_varint(rd) == v


def test_ping_online_and_offline():
    srv, port = _serve(_PingHandler)
    try:
        st = ping_server("127.0.0.1", port)
        assert st.online and st.players_online == 2 and st.player_names == ["steve"]
        assert st.version == "Paper 1.20.1" and st.motd == "메테노 서버"
        assert "🟢" in st.summary()
    finally:
        srv.shutdown()
    off = ping_server("127.0.0.1", 9, timeout=1)
    assert not off.online and "🔴" in off.summary()


def test_flatten_chat_and_parse_host():
    assert flatten_chat({"text": "a", "extra": ["b", {"text": "c"}]}) == "abc"
    assert parse_host("play.example.com:25566") == ("play.example.com", 25566)
    assert parse_host("localhost") == ("localhost", 25565)


# --- RCON ---------------------------------------------------------------------------------

class _RconHandler(socketserver.BaseRequestHandler):
    def handle(self):
        while True:
            hdr = self.request.recv(4)
            if not hdr:
                return
            (ln,) = struct.unpack("<i", hdr)
            raw = self.request.recv(ln)
            rid, kind = struct.unpack("<ii", raw[:8])
            body = raw[8:-2].decode()
            if kind == 3:
                pkt = struct.pack("<ii", rid if body == "secret" else -1, 2) + b"\x00\x00"
            else:
                out = "There are 2 of a max of 20 players online: a, b" if body == "list" else f"ran:{body}"
                pkt = struct.pack("<ii", rid, 0) + out.encode() + b"\x00\x00"
            self.request.sendall(struct.pack("<i", len(pkt)) + pkt)


def test_rcon_login_and_commands():
    srv, port = _serve(_RconHandler)
    try:
        with Rcon("127.0.0.1", port, "secret") as r:
            assert "players online" in r.command("list")
            assert r.command("say hi") == "ran:say hi"
        try:
            Rcon("127.0.0.1", port, "wrong").connect()
            assert False
        except RconAuthError:
            pass
    finally:
        srv.shutdown()


# --- Discord ------------------------------------------------------------------------------

def _fake_transport(log, me_id="99", messages=None):
    def t(method, url, headers, payload):
        log.append((method, url, payload))
        if url.endswith("/users/@me"):
            return 200, {"id": me_id, "username": "ARIUS"}
        if "/messages" in url and method == "GET":
            return 200, list(reversed(messages or []))  # API returns newest first
        if url.endswith("/typing"):
            return 204, None
        return 200, {"id": "m1"}
    return t


def test_webhook_announce_payload_and_errors():
    log = []
    c = DiscordClient(webhook_url="https://discord.com/api/webhooks/1/abc", username="ARIUS", transport=_fake_transport(log))
    out = c.announce(format_announcement("점검", "22시 재시작", "메테노서버"))
    assert "전송 완료" in out
    m, url, payload = log[-1]
    assert m == "POST" and url.startswith("https://discord.com/api/webhooks/1/abc") and "📢 점검" in payload["content"]
    try:
        DiscordClient(webhook_url="not a url")
        assert False
    except DiscordError:
        pass
    try:
        DiscordClient().announce("x")
        assert False
    except DiscordError as exc:
        assert "설정이 없습니다" in str(exc)


def test_discord_chat_replies_only_when_addressed():
    msgs = [
        {"id": "10", "content": "그냥 잡담", "author": {"id": "1", "username": "kim", "bot": False}, "mentions": []},
        {"id": "11", "content": "<@99> 서버 살아있어?", "author": {"id": "2", "username": "lee"}, "mentions": [{"id": "99"}]},
        {"id": "12", "content": "아리우스 안녕", "author": {"id": "3", "username": "park"}, "mentions": []},
        {"id": "13", "content": "나는 봇", "author": {"id": "99", "username": "ARIUS", "bot": True}, "mentions": []},
    ]
    log = []
    bot = DiscordBot("token", transport=_fake_transport(log, messages=msgs))
    seen = []
    chat = DiscordChat(bot, lambda text, m: seen.append(text) or f"답: {text}", ["123"], wake_words=["아리우스"], mention_only=True)
    chat.bootstrap()
    chat.last_ids["123"] = None  # pretend nothing was seen yet
    sent = chat.poll_once()
    assert sent == 2 and seen == ["서버 살아있어?", "안녕"]
    posts = [p for m, u, p in log if m == "POST" and u.endswith("/channels/123/messages")]
    assert [p["content"] for p in posts] == ["답: 서버 살아있어?", "답: 안녕"]
    assert chat.last_ids["123"] == "13"


# --- Voice wake word ---------------------------------------------------------------------

class _FakeTTS:
    def __init__(self):
        self.spoken = []

    def speak(self, text):
        self.spoken.append(text)
        return True


def test_wake_word_detection_and_awake_window():
    tts = _FakeTTS()
    vc = VoiceConversation(SpeechToText(), tts, lambda q: f"답: {q}", ["아리우스", "자비스"], awake_seconds=30)
    assert vc.detect_wake("아리 우스, 서버 상태 어때?") == (True, "서버 상태 어때")
    assert vc.detect_wake("오늘 날씨 어때")[0] is False
    assert vc.handle_utterance("오늘 날씨 어때") is None          # asleep, not addressed
    assert vc.handle_utterance("자비스") == "네, 말씀하세요."       # called -> ack, now awake
    assert vc.handle_utterance("서버 켜져 있어?") == "답: 서버 켜져 있어?"  # follow-up without name
    assert tts.spoken[-1] == "답: 서버 켜져 있어?"


# --- local server discovery ----------------------------------------------------------------


def test_guess_cwd_from_absolute_jar_or_launching_batch_file():
    from arius.minecraft import _guess_cwd

    assert _guess_cwd("java -jar C:\\Servers\\meteno\\paper.jar nogui") == "C:\\Servers\\meteno"
    assert _guess_cwd('java -Xmx4G -jar "C:\\My Server\\paper.jar" nogui') == "C:\\My Server"
    assert _guess_cwd("/usr/bin/java -jar /srv/mc/paper.jar") == "/srv/mc"
    # relative jar (the usual start.bat): the parent shell's batch file names the folder
    parent = 'C:\\Windows\\system32\\cmd.exe /c ""C:\\Servers\\meteno\\start.bat" "'
    assert _guess_cwd("java -Xmx4G -jar paper.jar nogui", parent) == "C:\\Servers\\meteno"
    assert _guess_cwd("java -jar paper.jar", "bash /home/me/server/start.sh") == "/home/me/server"
    assert _guess_cwd("java -jar paper.jar", "cmd.exe") == ""
    assert _guess_cwd("java -jar paper.jar") == ""


def test_find_server_processes_on_windows_reads_parent_batch_folder(monkeypatch):
    import sys

    from arius.minecraft import find_server_processes

    monkeypatch.setattr(sys, "platform", "win32")
    lines = [
        '4321|1500|C:\\Windows\\system32\\cmd.exe /c ""C:\\Servers\\meteno\\start.bat" "|java -Xmx4G -jar paper.jar nogui',
        "999|20||javaw -jar C:\\Games\\launcher.jar",  # not a server jar
        "777|900|C:\\Servers\\other\\paper.jar",  # legacy 3-field line, absolute jar without -jar: ignored
        "555|800|cmd.exe /c C:\\Servers\\old\\run.bat|java -jar spigot.jar",
        "not a line",
    ]
    calls = []
    run = lambda args, **kw: calls.append(args) or type("R", (), {"stdout": "\n".join(lines)})()  # noqa: E731
    procs = find_server_processes(run)
    assert calls and calls[0][0] == "powershell" and "ParentProcessId" in calls[0][-1]
    assert [(p.pid, p.memory_mb, p.cwd) for p in procs] == [
        (4321, 1500.0, "C:\\Servers\\meteno"),
        (555, 800.0, "C:\\Servers\\old"),
    ]
