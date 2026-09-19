from arius.config import AriusConfig, UserConfig
from arius.core import Arius
from arius.llm.echo_backend import EchoBackend
from arius.llm.base import Message
from arius.memory import Memory
from arius.permissions import PermissionManager, Role, Session, User
from arius.persona import build_system_prompt


def _owner_session():
    return Session(user=User("owner", Role.OWNER, "형"))


def test_tone_relationship_and_mood_in_prompt():
    cfg = AriusConfig()
    cfg.persona.tone = "casual"
    sp = build_system_prompt(cfg, _owner_session(), mood="걱정 — 서버가 꺼져 있다")
    assert "반말" in sp and "가장 가까운 사람" in sp and "걱정 — 서버가 꺼져 있다" in sp
    guest = PermissionManager().guest_session()
    assert "가장 가까운 사람" not in build_system_prompt(cfg, guest)
    cfg.persona.emotional = False
    assert "감정 표현" not in build_system_prompt(cfg, _owner_session(), mood="기쁨")


def test_default_tone_is_friendly_and_channels_adjust():
    cfg = AriusConfig()
    assert cfg.persona.tone == "friendly"
    assert "해요체" in build_system_prompt(cfg, _owner_session())
    assert "음성 대화" in build_system_prompt(cfg, _owner_session(), channel="voice")
    assert "디스코드 채팅" in build_system_prompt(cfg, _owner_session(), channel="discord")


def test_offline_replies_carry_emotion():
    be = EchoBackend("ARIUS")
    gen = lambda t: be.generate("", [Message("user", t)])  # noqa: E731
    greeting = gen("다녀왔어")
    assert any(w in greeting for w in ("반가워요", "어서 와요", "안녕하세요")), greeting
    tired = gen("오늘 너무 힘들다")
    assert "힘들" in tired or "쉬어요" in tired or "듣고 있을게요" in tired, tired
    happy = gen("나 오늘 해냈어!")
    assert "기뻐요" in happy or "축하" in happy, happy
    assert "곁에" in gen("사랑해")
    assert "오프라인" in gen("양자역학 설명해봐")  # fallback still admits it cannot reason


def test_mood_persists_and_reaches_the_prompt():
    cfg = AriusConfig(users=[UserConfig("owner", "owner", "형")])
    a = Arius(cfg, memory=Memory(":memory:"))
    a.login("owner")
    assert a.current_mood() == ""
    a.set_mood("안도와 기쁨 — 서버가 다시 살아났다")
    assert "안도" in a.current_mood()
    assert "안도와 기쁨" in build_system_prompt(cfg, a.session, mood=a.current_mood())


def test_heartbeat_sets_mood_on_server_transition():
    from arius.agent.heartbeat import Heartbeat
    from arius.agent.loop import AgentLoop
    from arius.agent.tools import SYSTEM_USER, ToolContext, build_registry
    from arius.minecraft import ServerStatus

    cfg = AriusConfig(users=[UserConfig("u", "admin")])
    mem = Memory(":memory:")
    ctx = ToolContext(config=cfg, memory=mem, session=PermissionManager.from_config(cfg).authenticate("u"),
                      pinger=lambda h, p: ServerStatus(h, p, True), process_finder=lambda: [])
    hb = Heartbeat(lambda: AgentLoop(EchoBackend(), build_registry(), ctx), ctx)
    hb._server_transition(True)
    hb._server_transition(False)
    moods = {f.key: f.value for f in mem.list_facts(SYSTEM_USER)}
    assert "걱정" in moods["mood"]
    hb._server_transition(True)
    assert "안도" in {f.key: f.value for f in mem.list_facts(SYSTEM_USER)}["mood"]
