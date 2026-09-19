"""Agent loop, autonomy gate, tools refusal, heartbeat rules — all offline with fakes."""

import json
import tempfile
import threading
from pathlib import Path

from arius.agent.heartbeat import Heartbeat
from arius.agent.loop import AgentLoop, parse_action
from arius.agent.tools import Refused, ToolContext, build_registry
from arius.config import AriusConfig, UserConfig
from arius.core import Arius
from arius.discord import DiscordClient
from arius.llm.base import LLMBackend
from arius.memory import Memory
from arius.minecraft import ServerStatus
from arius.permissions import PermissionManager


class ScriptedBackend(LLMBackend):
    """Replies with a fixed sequence of JSON actions, then a final."""

    name = "scripted"

    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = 0

    def generate(self, system, messages):
        self.calls += 1
        return self.replies.pop(0) if self.replies else json.dumps({"final": "끝"})


def make_ctx(role="admin", online=True, discord_calls=None, tmp=None, db_path=":memory:"):
    cfg = AriusConfig(users=[UserConfig("u", role)])
    cfg.minecraft.name = "메테노서버"
    if tmp:
        cfg.minecraft.server_dir = str(tmp)
    mem = Memory(db_path)
    session = PermissionManager.from_config(cfg).authenticate("u")
    discord_calls = discord_calls if discord_calls is not None else []

    def transport(m, u, h, p):
        discord_calls.append((m, u, p))
        return 200, {"id": "1"}

    ctx = ToolContext(
        config=cfg, memory=mem, session=session, notify=lambda m: None,
        pinger=lambda h, p: ServerStatus(h, p, online, 1, 20, ["steve"], "Paper", "hi"),
        process_finder=lambda: [],
        discord_factory=lambda: DiscordClient(webhook_url="https://discord.com/api/webhooks/1/x", transport=transport),
        snapshot_fn=lambda: {"time": "t", "os": "test", "cpu": {"cores": 4, "load_pct": 1.0},
                             "memory": {"total_mb": 1000, "available_mb": 100, "used_pct": 90.0},
                             "disks": [{"path": "/", "total_gb": 100, "free_gb": 5, "used_pct": 95.0}],
                             "uptime_hours": 1, "top_processes": []},
    )
    return cfg, mem, session, ctx


def test_registry_has_no_shell_or_destructive_file_tools():
    names = set(build_registry())
    assert not names & {"run_command", "delete_file", "write_file", "move_file"}
    assert {"minecraft_status", "minecraft_command", "discord_announce", "system_status"} <= names


def test_parse_action_tolerates_prose_and_fences():
    assert parse_action('생각해보니… {"thought":"x","action":"minecraft_status","args":{}} 끝')["action"] == "minecraft_status"
    assert parse_action('```json\n{"final": "이상 없음"}\n```')["final"] == "이상 없음"
    assert parse_action("그냥 텍스트") is None
    assert parse_action('{"unrelated": 1}') is None


def test_loop_observes_then_finishes():
    cfg, mem, session, ctx = make_ctx()
    be = ScriptedBackend([json.dumps({"thought": "확인", "action": "minecraft_status", "args": {}}), json.dumps({"final": "서버 정상"})])
    res = AgentLoop(be, build_registry(), ctx, autonomy="supervised").run("서버 봐줘")
    assert res.final == "서버 정상" and res.actions_taken == 1
    assert res.steps[0]["status"] == "ok" and "메테노서버" in res.steps[0]["observation"]


def test_observe_mode_refuses_state_changes():
    cfg, mem, session, ctx = make_ctx()
    be = ScriptedBackend([json.dumps({"action": "discord_announce", "args": {"title": "t", "body": "b"}})])
    res = AgentLoop(be, build_registry(), ctx, autonomy="observe").run("공지해")
    assert res.denied == 1 and res.actions_taken == 0
    assert "observe" in res.steps[0]["observation"]


def test_supervised_asks_and_respects_answer():
    cfg, mem, session, ctx = make_ctx()
    asked = []
    be = ScriptedBackend([json.dumps({"action": "discord_announce", "args": {"title": "t", "body": "b"}})])
    res = AgentLoop(be, build_registry(), ctx, autonomy="supervised", confirm=lambda d: asked.append(d) or True).run("공지")
    assert asked and res.actions_taken == 1
    be = ScriptedBackend([json.dumps({"action": "discord_announce", "args": {"title": "t", "body": "b"}})])
    res = AgentLoop(be, build_registry(), ctx, autonomy="supervised", confirm=lambda d: False).run("공지")
    assert res.actions_taken == 0 and res.steps[0]["status"] == "confirm_no"


def test_autonomous_runs_only_auto_allowed_tools_without_asking():
    cfg, mem, session, ctx = make_ctx()
    be = ScriptedBackend([
        json.dumps({"action": "discord_announce", "args": {"title": "a", "body": "b"}}),  # allowed
        json.dumps({"action": "minecraft_stop", "args": {}}),  # danger, not allowed -> asks -> denied
    ])
    res = AgentLoop(be, build_registry(), ctx, autonomy="autonomous", auto_allow=["discord_announce"], confirm=lambda d: False).run("x")
    assert res.actions_taken == 1 and res.denied == 1
    assert res.steps[1]["tool"] == "minecraft_stop" and res.steps[1]["status"] == "confirm_no"


def test_rbac_still_applies_inside_agent():
    cfg, mem, session, ctx = make_ctx(role="user")  # user has mc.read but not mc.admin
    be = ScriptedBackend([json.dumps({"action": "minecraft_say", "args": {"message": "hi"}})])
    res = AgentLoop(be, build_registry(), ctx, autonomy="autonomous", auto_allow=["minecraft_say"]).run("x")
    assert res.denied == 1 and "권한 없음" in res.steps[0]["observation"]


def test_rcon_allowlist_and_missing_password():
    cfg, mem, session, ctx = make_ctx()
    tools = build_registry()
    try:
        tools["minecraft_command"].handler(ctx, {"command": "execute as @a run kill"})
        assert False, "should refuse"
    except Refused as exc:
        assert "허용되지 않은" in str(exc)
    try:
        tools["minecraft_command"].handler(ctx, {"command": "list"})
        assert False, "should refuse without password"
    except Refused as exc:
        assert "RCON 암호" in str(exc)


def test_file_tools_are_read_only_and_confined():
    with tempfile.TemporaryDirectory() as tmp:
        Path(tmp, "server.properties").write_text("motd=x\n")
        cfg, mem, session, ctx = make_ctx(tmp=tmp)
        tools = build_registry()
        assert "server.properties" in tools["list_dir"].handler(ctx, {"path": tmp})
        assert "motd=x" in tools["read_file"].handler(ctx, {"path": str(Path(tmp, "server.properties"))})
        outside = str(Path(tmp).parent / "outside-the-server-folder.txt")  # any path not under an allowed root
        try:
            tools["read_file"].handler(ctx, {"path": outside})
            assert False
        except Refused as exc:
            assert "허용 폴더 밖" in str(exc)


def test_heartbeat_rules_offline_notify_and_restart_policy(tmp_path):
    calls = []
    cfg, mem, session, ctx = make_ctx(online=False, discord_calls=calls)
    started = []
    ctx.server_starter = lambda d, c: started.append(d) or "서버 시작 명령을 실행했습니다: x"
    server_dir = str(tmp_path)  # platform-neutral: not "/tmp", which Windows renders as "\\tmp"
    cfg.minecraft.server_dir = server_dir
    mem.add_policy("디스크 85% 넘으면 알려줘")
    mem.add_policy("서버 꺼지면 다시 켜고 디스코드에 공지해")
    from arius.llm.echo_backend import EchoBackend
    notes = []
    ctx.notify = notes.append
    hb = Heartbeat(lambda: AgentLoop(EchoBackend(), build_registry(), ctx, autonomy="autonomous",
                                     auto_allow=["discord_announce", "minecraft_start"]), ctx)
    report = hb.run_once()
    assert "규칙 기반 조치" in report
    assert any("디스크" in n for n in notes)
    assert started == [server_dir] and calls  # restarted + announced on Discord
    assert mem.agent_log()[-1]["kind"] == "heartbeat"


def test_heartbeat_background_thread_uses_memory_built_on_main_thread(tmp_path):
    """`python main.py agent`: Memory is opened on the main thread, the tick runs on another.

    Regression for "SQLite objects created in a thread can only be used in that same thread".
    """
    cfg, mem, session, ctx = make_ctx(online=True, db_path=tmp_path / "arius.db")
    from arius.llm.echo_backend import EchoBackend
    events = []
    ticked = threading.Event()

    def on_event(msg):
        events.append(msg)
        if msg.startswith("점검"):
            ticked.set()

    hb = Heartbeat(lambda: AgentLoop(EchoBackend(), build_registry(), ctx), ctx, on_event=on_event)
    hb.start()
    try:
        assert ticked.wait(10), "first heartbeat tick never reported"
    finally:
        hb.stop()
        hb._thread.join(10)
    assert not any(e.startswith("점검 오류") for e in events), events
    assert any(e.startswith("점검: 이상 없음") for e in events), events
    assert mem.agent_log()[-1]["kind"] == "heartbeat"  # written by the other thread, read here
    # /agent run from the REPL uses the same Heartbeat (and Memory) on the main thread
    assert "이상 없음" in hb.run_once()
    mem.close()


def test_heartbeat_detects_server_transition_once():
    cfg, mem, session, ctx = make_ctx(online=True)
    from arius.llm.echo_backend import EchoBackend
    hb = Heartbeat(lambda: AgentLoop(EchoBackend(), build_registry(), ctx), ctx)
    assert hb._server_transition(True) == ""      # first observation: no event
    assert "오프라인" in hb._server_transition(False)
    assert hb._server_transition(False) == ""     # unchanged: silent
    assert "온라인" in hb._server_transition(True)


def test_arius_routes_requests_to_agent_only_with_real_backend():
    cfg = AriusConfig(users=[UserConfig("owner", "owner")])
    a = Arius(cfg, memory=Memory(":memory:"))
    a.login("owner")
    assert Arius.is_agent_request("서버 로그에서 오류 찾아줘")
    assert not Arius.is_agent_request("안녕")
    assert a.handle("서버 로그에서 오류 찾아줘").source.startswith("skill:")  # echo backend: no agent routing
    a.backend = ScriptedBackend([json.dumps({"final": "확인했어요"})])
    r = a.handle("이상한 프로세스 있는지 봐줘")
    assert r.source == "agent" and r.text == "확인했어요"
