"""The operating rules ("운영 규칙"): response formats, confirmations, memory rules,
secrets, modes, PC control, inspection and backups — all offline with fakes."""

import json
import tempfile
import time
from pathlib import Path

from arius.agent.heartbeat import Heartbeat
from arius.agent.loop import AgentLoop
from arius.agent.tools import SYSTEM_USER, ToolContext, build_registry, restart_precheck
from arius.config import AriusConfig, UserConfig, config_to_dict, _coerce
from arius.core import Arius
from arius.desktop import Desktop, is_url
from arius.llm.base import LLMBackend
from arius.llm.echo_backend import EchoBackend
from arius.memory import Memory
from arius.minecraft import ServerStatus
from arius.modes import MODES, parse_mode
from arius.permissions import PermissionManager, Role, Session, User
from arius.persona import build_system_prompt
from arius.privacy import looks_secret, redact
from arius.voice import TextToSpeech, VoiceConversation, speakable


class Scripted(LLMBackend):
    name = "scripted"

    def __init__(self, replies):
        self.replies = list(replies)

    def generate(self, system, messages):
        return self.replies.pop(0) if self.replies else json.dumps({"final": "끝"})


class FakeRcon:
    log: list[str] = []

    def __init__(self, replies=None):
        self.replies = replies or {}

    def __enter__(self):
        return self

    def __exit__(self, *a):
        pass

    def command(self, cmd):
        FakeRcon.log.append(cmd)
        return self.replies.get(cmd.split()[0], "ok")


def make(role="owner", online=True, players=1, tmp=None, rcon=True, snapshot=None):
    cfg = AriusConfig(users=[UserConfig("u", role, "형")])
    cfg.minecraft.name = "메테노서버"
    cfg.minecraft.rcon_password = "pw" if rcon else ""
    if tmp:
        cfg.minecraft.server_dir = str(tmp)
    a = Arius(cfg, memory=Memory(":memory:"))
    a.login("u")
    snap = snapshot or {"time": "t", "os": "test", "cpu": {"cores": 4, "load_pct": 10.0},
                        "memory": {"total_mb": 16000, "available_mb": 8000, "used_pct": 50.0},
                        "disks": [{"path": "/", "total_gb": 500, "free_gb": 200, "used_pct": 60.0}],
                        "uptime_hours": 5, "top_processes": [{"pid": 1, "mem_mb": 100.0, "name": "java"}]}
    FakeRcon.log = []
    calls = []
    desk = Desktop({"내 게임": "C:/g.exe"}, {}, home=tmp or ".", platform="win32", protected=["java", "python"],
                   run=lambda args, **k: calls.append(args) or type("R", (), {"returncode": 0, "stdout": "True", "stderr": ""})(),
                   popen=lambda c, cwd=None: calls.append(c), browser=lambda u: calls.append(u) or True,
                   opener=lambda p: calls.append(("open", p)))
    a.tool_context = lambda session=None, _a=a: ToolContext(  # type: ignore[method-assign]
        config=_a.config, memory=_a.memory, session=session or _a.session, notify=_a.notify,
        pinger=lambda h, p: ServerStatus(h, p, online, players, 20, ["steve"] if players else [], "Paper 1.20.1", "hi"),
        process_finder=lambda: [], rcon_factory=lambda h, p, pw: FakeRcon({"tps": "TPS from last 1m, 5m, 15m: 19.8, 19.9, 20.0", "list": "There are 1 of a max of 20 players online: steve"}),
        snapshot_fn=lambda: snap, desktop_factory=lambda: desk, sleeper=lambda s: None, background=False,
    )
    return a, calls


# --- secrets ------------------------------------------------------------------------------


def test_secrets_are_detected_redacted_and_never_stored_or_spoken():
    assert looks_secret("비밀번호는 hunter2") and looks_secret("api key = sk-abcdefghijklmnopqrstu")
    assert looks_secret("카드번호 1234 5678 9012 3456") and looks_secret("토큰 ghp_abcdefghijklmnopqrstuvwxyz1234")
    assert not looks_secret("내 생일은 3월 2일") and not looks_secret("암호화폐 이야기")
    assert not looks_secret("백업 파일은 world-20260919-094717.zip") and not looks_secret("전화 010-1234-5678")
    assert looks_secret("RCON 설정: mypass") and "mypass" not in redact("RCON 설정: mypass")
    assert "s3cret" not in redact('{"password": "s3cret", "port": 25575}')
    assert "hunter2" not in redact("비밀번호는 hunter2") and "[비밀 정보 생략]" in redact("password=abc")
    a, _ = make()
    r = a.handle("기억해: 디스코드 토큰은 abc.def.ghi")
    assert r.text.startswith("실행하지 않았습니다") and "비밀" in r.text
    assert a.memory.list_facts("u") == []
    logged = a.memory.recent_messages("u")
    assert logged and "abc.def.ghi" not in logged[0]["content"]
    assert "hunter2" not in speakable("네, 비밀번호는 hunter2 입니다")
    # the agent tool refuses too
    ctx = a.tool_context()
    assert "실행하지 않았습니다" in build_registry()["remember"].handler(ctx, {"key": "api key", "value": "sk-abcdefghijklmnopqrstu"})


# --- memory rules ---------------------------------------------------------------------------


def test_learn_reports_in_charter_format_with_metadata():
    a, _ = make()
    r = a.handle("이것을 기억해: 내 서버 IP는 메테노서버 localhost")
    assert r.source == "skill:learn"
    for part in ("새로 기억한 내용", "근거 및 신뢰도", "앞으로 달라지는 동작", "사용자에게 필요한 승인", "삭제 또는 수정 방법"):
        assert part in r.text
    facts = a.memory.list_facts("u")
    assert facts[0].source == "user" and facts[0].confidence == 1.0 and facts[0].confirmed_ts > 0
    assert "출처 사용자" in facts[0].meta() and "신뢰도 100%" in facts[0].meta()
    listing = a.handle("네가 기억하는 내용을 보여줘")
    assert listing.source == "skill:facts" and "저장 20" in listing.text and "출처 사용자" in listing.text


def test_forget_one_and_forget_all_requires_confirmation():
    a, _ = make()
    a.handle("기억해: 생일은 3월 2일")
    a.handle("기억해: 취미는 슈트 제작")
    assert "완료했습니다" in a.handle("기억 삭제: 생일").text
    assert [f.key for f in a.memory.list_facts("u")] == ["취미"]
    assert "실행하지 않았습니다" in a.handle("기억 삭제: 없는것").text
    a.handle("기억해: 색깔은 파랑")
    assert "'색깔' 기억을 지웠습니다" in a.handle("이 기억을 삭제해").text  # the most recent one
    ask = a.handle("내 정보를 모두 잊어")
    assert ask.text.startswith("실행 예정") and "진행할까요" in ask.text
    assert a.memory.list_facts("u")  # nothing deleted yet
    done = a.handle("네, 모두 잊어")
    assert done.text.startswith("완료했습니다") and a.memory.list_facts("u") == []
    # a stray confirmation with no pending request is refused
    assert "실행하지 않았습니다" in a.handle("네, 모두 잊어").text


def test_memory_migration_adds_metadata_columns_to_old_db():
    import sqlite3

    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp, "old.db")
        con = sqlite3.connect(db)
        con.execute("CREATE TABLE facts (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT NOT NULL, key TEXT NOT NULL, value TEXT NOT NULL, tags TEXT NOT NULL DEFAULT '', ts REAL NOT NULL, UNIQUE(username, key))")
        con.execute("INSERT INTO facts (username, key, value, ts) VALUES ('o', '생일', '3월', 1)")
        con.commit()
        con.close()
        m = Memory(db)
        f = m.list_facts("o")[0]
        assert f.source == "user" and f.confidence == 1.0 and f.confirmed_ts == 0
        assert m.confirm_fact("o", "생일") and m.list_facts("o")[0].confirmed_ts > 0
        m.close()


# --- response formats & refusals -----------------------------------------------------------


def test_refusal_uses_not_done_format():
    a, _ = make(role="guest")
    r = a.handle("/exec ls")
    assert r.text.startswith("실행하지 않았습니다") and "이유:" in r.text and "다음 조치:" in r.text


def test_persona_prompt_carries_the_charter():
    cfg = AriusConfig(assistant_name="자비스")
    cfg.voice.wake_words = ["자비스"]
    sp = build_system_prompt(cfg, Session(user=User("owner", Role.OWNER, "형")), mode="fast")
    for phrase in ("네, 말씀하세요.", "잘 듣지 못했습니다", "실행하겠습니다:", "실행 예정:", "완료했습니다.", "실행하지 않았습니다.",
                   "절대 금지", "재학습", "장기 기억", "약 5분 후 재시작", "빠른 모드", "메테노디코", "호출어는 '자비스'"):
        assert phrase in sp, phrase


# --- confirmation gate ----------------------------------------------------------------------


def test_kick_and_op_always_ask_even_when_command_tool_is_auto_allowed():
    a, _ = make(role="admin")
    ctx = a.tool_context()
    assert ctx.rcon_needs_confirmation("kick steve") and ctx.rcon_needs_confirmation("whitelist remove steve")
    assert ctx.rcon_needs_confirmation("op steve") and not ctx.rcon_needs_confirmation("whitelist add steve")
    assert not ctx.rcon_needs_confirmation("list") and not ctx.rcon_needs_confirmation("say hi")
    asked = []
    be = Scripted([json.dumps({"action": "minecraft_command", "args": {"command": "kick steve"}}),
                   json.dumps({"action": "minecraft_command", "args": {"command": "list"}})])
    res = AgentLoop(be, build_registry(), ctx, autonomy="autonomous", auto_allow=["minecraft_command"],
                    confirm=lambda d: asked.append(d) or False).run("x")
    assert len(asked) == 1 and "실행 예정" in asked[0] and "영향" in asked[0] and "kick" in asked[0]
    assert res.steps[0]["status"] == "confirm_no" and res.steps[1]["status"] == "ok"
    assert FakeRcon.log == ["list"]


def test_typed_kick_asks_and_bang_confirms():
    a, _ = make(role="admin")
    ask = a.handle("서버 명령: kick steve")
    assert ask.text.startswith("실행 예정") and FakeRcon.log == []
    a.handle("서버 명령: kick steve !")
    assert FakeRcon.log == ["kick steve"]


def test_approval_learning_suggests_auto_allow_after_three_yes():
    a, _ = make(role="admin")
    ctx = a.tool_context()
    a.memory.log_agent("action", "minecraft_enable_rcon", '{"password": "s3cret"} → ok')
    assert "s3cret" not in a.memory.agent_log()[-1]["detail"]
    events = []
    for _ in range(3):
        be = Scripted([json.dumps({"action": "minecraft_say", "args": {"message": "hi"}})])
        AgentLoop(be, build_registry(), ctx, autonomy="supervised", confirm=lambda d: True, on_event=events.append).run("x")
    assert a.memory.approval_stats("minecraft_say") == (3, 0)
    assert any("자동 허용 추가: minecraft_say" in e for e in events)
    # a refusal breaks the streak: no candidate any more
    be = Scripted([json.dumps({"action": "minecraft_say", "args": {"message": "hi"}})])
    AgentLoop(be, build_registry(), ctx, autonomy="supervised", confirm=lambda d: False).run("x")
    assert a.memory.approval_candidates(3) == []


def test_auto_allow_skill_manages_list_and_refuses_danger_tools():
    a, _ = make()
    r = a.handle("자동 허용 추가: minecraft_backup")
    assert r.text.startswith("완료했습니다") and "minecraft_backup" in a.config.agent.auto_allow
    assert "실행하지 않았습니다" in a.handle("자동 허용 추가: minecraft_restart").text
    assert "실행하지 않았습니다" in a.handle("자동 허용 추가: nope").text
    assert "minecraft_backup" in a.handle("자동 허용 목록").text
    assert "완료했습니다" in a.handle("자동 허용 삭제: minecraft_backup").text
    assert "minecraft_backup" not in a.config.agent.auto_allow


def test_save_config_roundtrip_and_new_fields():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp, "config.json")
        cfg = AriusConfig(users=[UserConfig("o", "owner")])
        cfg.desktop.programs["내 게임"] = "C:/g.exe"
        cfg.agent.rcon_confirm.append("give")
        path.write_text(json.dumps(config_to_dict(cfg), ensure_ascii=False), encoding="utf-8")
        a = Arius.from_path(str(path))
        assert a.config_path == path and a.config.desktop.programs == {"내 게임": "C:/g.exe"} and "give" in a.config.agent.rcon_confirm
        a.config.agent.auto_allow.append("minecraft_backup")
        assert a.save_config()
        assert "minecraft_backup" in _coerce(json.loads(path.read_text(encoding="utf-8"))).agent.auto_allow
        a.close()


# --- server: restart pre-checks, players, backups, inspection ---------------------------------


def test_restart_asks_with_precheck_then_confirms_with_notice():
    with tempfile.TemporaryDirectory() as tmp:
        Path(tmp, "server.properties").write_text("level-name=world\n")
        a, _ = make(tmp=tmp)
        pre, info = restart_precheck(a.tool_context())
        assert "현재 접속자: 1명" in pre and "최근 백업: 없음" in pre and info["players"] == 1
        ask = a.handle("서버 재시작")
        assert ask.text.startswith("실행 예정") and "접속자" in ask.text and "진행할까요" in ask.text and FakeRcon.log == []
        stop_ask = a.handle("서버 중지")
        assert "실행 예정" in stop_ask.text and "서버 중지 확인" in stop_ask.text
        started = []
        ctx_factory = a.tool_context
        a.tool_context = lambda s=None: _with_starter(ctx_factory(s), started)  # type: ignore[method-assign]
        done = a.handle("서버 재시작 확인")
        assert done.text.startswith("실행하겠습니다") and "약 5분 후 재시작됩니다" in done.text
        assert FakeRcon.log[0].startswith("say 서버가 약 5분 후 재시작됩니다") and "stop" in FakeRcon.log


def _with_starter(ctx, started):
    ctx.server_starter = lambda d, c: started.append(d) or "서버 시작 명령을 실행했습니다: x"

    def ping(h, p):  # online until "stop" was sent, offline until the starter ran
        on = "stop" not in FakeRcon.log or bool(started)
        return ServerStatus(h, p, on, 1, 20, ["steve"], "Paper", "hi")

    ctx.pinger = ping
    return ctx


def test_player_lists_backup_and_backup_status():
    with tempfile.TemporaryDirectory() as tmp:
        Path(tmp, "server.properties").write_text("level-name=world\n")
        Path(tmp, "whitelist.json").write_text(json.dumps([{"uuid": "1", "name": "steve"}]))
        Path(tmp, "ops.json").write_text(json.dumps([{"uuid": "1", "name": "형", "level": 4}]))
        Path(tmp, "banned-players.json").write_text(json.dumps([{"name": "griefer", "reason": "griefing"}]))
        Path(tmp, "world", "region").mkdir(parents=True)
        Path(tmp, "world", "level.dat").write_bytes(b"x" * 100)
        Path(tmp, "world", "region", "r.0.0.mca").write_bytes(b"y" * 100)
        Path(tmp, "world", "session.lock").write_bytes(b"z")
        a, _ = make(tmp=tmp)
        assert "steve" in a.handle("화이트리스트").text
        ops = a.handle("운영자 목록").text
        assert "형 (레벨 4)" in ops
        assert "griefer — griefing" in a.handle("밴 목록").text
        assert "백업 없음" in a.handle("백업 상태").text
        r = a.handle("서버 백업")
        assert "완료했습니다" in r.text and "2개 파일" in r.text and FakeRcon.log == ["save-all flush"]
        zips = list(Path(tmp, "backups").glob("world-*.zip"))
        assert len(zips) == 1
        assert "최근 백업" in a.handle("백업 상태").text and "🟢" in a.handle("백업 상태").text
        # nothing deleted, second backup adds a file
        time.sleep(1.1)
        a.handle("서버 백업")
        assert len(list(Path(tmp, "backups").glob("world-*.zip"))) == 2
        assert Path(tmp, "world", "session.lock").exists()


def test_server_inspection_runs_seven_steps_with_priorities():
    with tempfile.TemporaryDirectory() as tmp:
        Path(tmp, "server.properties").write_text("level-name=world\n")
        Path(tmp, "logs").mkdir()
        Path(tmp, "logs", "latest.log").write_text("\n".join(["[12:00:00] [Server thread/ERROR]: boom"] * 6 + ["[12:01:00] [Server thread/INFO]: ok"]))
        a, _ = make(tmp=tmp, snapshot={"time": "t", "os": "test", "cpu": {"cores": 4, "load_pct": 10.0},
                                         "memory": {"total_mb": 16000, "available_mb": 8000, "used_pct": 50.0},
                                         "disks": [{"path": "/", "total_gb": 500, "free_gb": 20, "used_pct": 96.0}],
                                         "uptime_hours": 5, "top_processes": []})
        r = a.handle("서버 점검해")
        assert r.source == "skill:inspect"
        for step in ("1. 서버 온라인 상태", "2. 접속자 수", "3. TPS", "4. CPU/RAM", "5. 디스크", "6. 최근 오류 로그", "7. 최신 백업"):
            assert step in r.text, step
        assert "19.8 TPS" in r.text and "🔴 즉시 조치" in r.text and "디스크" in r.text and "오류 6건" in r.text
        pc = a.handle("PC 점검")
        assert "[PC 점검]" in pc.text and "🔴 디스크" in pc.text
        both = a.handle("전체 점검")
        assert "[PC 점검]" in both.text and "[메테노서버 점검]" in both.text


def test_heartbeat_builtin_alerts_fire_once_per_condition():
    a, _ = make(snapshot={"time": "t", "os": "test", "cpu": {"cores": 4, "load_pct": 99.0},
                          "memory": {"total_mb": 1000, "available_mb": 50, "used_pct": 95.0},
                          "disks": [{"path": "/", "total_gb": 100, "free_gb": 2, "used_pct": 98.0}],
                          "uptime_hours": 1, "top_processes": []})
    ctx = a.tool_context()
    events = []
    ctx.notify = events.append
    hb = Heartbeat(lambda: AgentLoop(EchoBackend(), build_registry(), ctx), ctx, on_event=events.append)
    hb.run_once()
    alerts = [e for e in events if e.startswith("⚠️")]
    assert any("디스크" in e for e in alerts) and any("메모리" in e for e in alerts) and any("CPU" in e for e in alerts)
    assert all("권장" in e for e in alerts)
    events.clear()
    hb.run_once()
    assert not [e for e in events if e.startswith("⚠️")]  # same conditions: silent
    assert {f.key for f in a.memory.list_facts(SYSTEM_USER)} >= {"alerts.active"}


# --- modes -----------------------------------------------------------------------------------


def test_modes_switch_persist_and_shape_prompt_and_agent():
    a, _ = make()
    assert a.current_mode() == "accurate" and parse_mode("빠른 모드") == "fast" and parse_mode("zzz") is None
    changes = []
    a.on_mode_change = changes.append
    r = a.handle("빠른 모드로")
    assert r.source == "skill:mode" and "빠른 모드" in r.text and a.current_mode() == "fast" and changes == ["fast"]
    assert a.agent_loop().max_steps == MODES["fast"].max_steps
    assert "빠른 모드입니다" in build_system_prompt(a.config, a.session, mode=a.current_mode())
    assert "▶ 빠른 모드" in a.handle("현재 모드").text
    sleep = a.handle("/mode 절전")
    assert "절전 모드" in sleep.text and a.current_mode() == "sleep"
    inspect = a.handle("점검 모드")
    assert "[PC 점검]" in inspect.text and "[메테노서버 점검]" in inspect.text
    learn = a.handle("학습 모드")
    assert "[학습 보고]" in learn.text and "새로 기억한 내용" in learn.text
    assert "[학습 보고]" in a.handle("학습 보고").text
    # survives a new Arius on the same memory
    b = Arius(a.config, memory=a.memory)
    assert b.current_mode() == "learn"


# --- PC control ----------------------------------------------------------------------------


def test_desktop_skill_opens_launches_switches_and_confirms_close():
    with tempfile.TemporaryDirectory() as tmp:
        Path(tmp, "Downloads").mkdir()
        a, calls = make(tmp=tmp)
        assert "https://www.youtube.com" in a.handle("유튜브 열어줘").text and calls[-1] == "https://www.youtube.com"
        assert "완료했습니다" in a.handle("naver.com 열어").text and calls[-1] == "https://naver.com"
        assert "'메모장' 을(를) 실행" in a.handle("메모장 실행해").text and calls[-1] == "notepad"
        assert "실행했습니다" in a.handle("내 게임 켜줘").text and calls[-1] == "C:/g.exe"
        assert "Downloads" in a.handle("다운로드 폴더 열어").text
        assert "'크롬' 창으로 전환" in a.handle("창 전환: 크롬").text
        assert "실행 중인 프로그램" in a.handle("실행 중인 프로그램").text
        ask = a.handle("notepad 종료해")
        assert ask.text.startswith("실행 예정") and "종료 확인: notepad" in ask.text and ["taskkill", "/IM", "notepad.exe"] not in calls
        done = a.handle("종료 확인: notepad")
        assert done.text.startswith("완료했습니다") and calls[-1] == ["taskkill", "/IM", "notepad.exe"]
        assert "보호된 프로세스" in a.handle("프로그램 종료: java").text
        unknown = a.handle("포토샵 열어줘")
        assert unknown.text.startswith("실행하지 않았습니다") and "desktop.programs" in unknown.text
        assert "서버 폴더 열기" in a.handle("서버 폴더 열어줘").text and calls[-1] == ("open", str(Path(tmp)))
        # not confused with server / memory commands
        assert a.handle("서버 켜줘").source == "skill:minecraft"
        assert a.handle("기억해: 문 열어").source == "skill:learn"


def test_desktop_permissions_and_url_policy():
    a, calls = make(role="user")  # USER has no desktop.open
    assert a.handle("유튜브 열어줘").source.startswith("denied:")
    a, calls = make(role="operator")  # OPERATOR: open yes, close no
    assert a.handle("유튜브 열어줘").source == "skill:desktop"
    assert "desktop.manage" in a.handle("notepad 종료해").text
    d = Desktop(sites={"내 사이트": "https://example.com/x"}, allow_any_url=False, platform="win32", browser=lambda u: True)
    assert "완료" in d.open_url("내 사이트") and "완료" in d.open_url("https://example.com/other")
    assert "허용되지 않은" in d.open_url("https://evil.example.org")
    assert is_url("github.com") and not is_url("메모장") and not is_url("C:/Games")


# --- voice ------------------------------------------------------------------------------------


def test_voice_ack_and_unclear_phrases_follow_the_rules():
    spoken = []

    class Stt:
        available = True
        reason = None

        def __init__(self):
            self.items = ["자비스", "", "", "지금 몇 시야"]

        def listen(self):
            return self.items.pop(0) if self.items else None

    tts = TextToSpeech(backend=None)
    tts.speak = lambda t: spoken.append(t) or True  # type: ignore[method-assign]
    vc = VoiceConversation(Stt(), tts, lambda q: "답변", ["자비스"], awake_seconds=30)
    assert vc.handle_unclear() is None  # not awake: ignore background noise
    assert vc.handle_utterance("자비스") == "네, 말씀하세요."
    assert vc.handle_unclear() == "잘 듣지 못했습니다. 다시 말씀해 주시겠어요?"
    assert spoken == ["네, 말씀하세요.", "잘 듣지 못했습니다. 다시 말씀해 주시겠어요?"]
