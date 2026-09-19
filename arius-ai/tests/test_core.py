from arius.config import AriusConfig, UserConfig
from arius.core import Arius
from arius.memory import Memory
from arius.permissions import Role


def make_arius() -> Arius:
    config = AriusConfig(
        users=[
            UserConfig(username="owner", role="owner", display_name="오너"),
            UserConfig(username="kid", role="guest", display_name="게스트"),
        ]
    )
    # in-memory DB so tests never touch disk
    return Arius(config, memory=Memory(":memory:"))


def test_guest_denied_exec():
    arius = make_arius()
    arius.login("kid")
    reply = arius.handle("/exec ls")
    assert reply.source.startswith("denied:")
    assert "권한" in reply.text


def test_owner_can_exec():
    arius = make_arius()
    arius.login("owner")
    reply = arius.handle("/exec echo hello")
    assert reply.source == "skill:exec"
    assert "hello" in reply.text
    assert "종료 코드: 0" in reply.text


def test_learn_and_recall_flow():
    arius = make_arius()
    arius.login("owner")
    r1 = arius.handle("기억해: 내 프로젝트는 슈트 제작")
    assert r1.source == "skill:learn"
    r2 = arius.handle("내 프로젝트 뭐였지 기억나?")
    assert r2.source == "skill:recall"
    assert "슈트" in r2.text


def test_guest_cannot_learn():
    arius = make_arius()
    arius.login("kid")
    r = arius.handle("기억해: 비밀번호는 1234")
    assert r.source.startswith("denied:")


def test_help_lists_only_permitted_skills():
    arius = make_arius()
    arius.login("kid")  # guest
    r = arius.handle("/help")
    assert "exec" not in r.text  # guest can't see exec
    arius.login("owner")
    r2 = arius.handle("/help")
    assert "exec" in r2.text


def test_freeform_chat_uses_llm_backend():
    arius = make_arius()
    arius.login("owner")
    r = arius.handle("자기소개 좀 해줘")
    assert r.source.startswith("llm:")
    assert r.text  # echo backend always returns something


def test_project_requires_manage_capability():
    arius = make_arius()
    arius.login("kid")
    denied = arius.handle("프로젝트 생성 슈트")
    assert denied.source.startswith("denied:")
    arius.login("owner")
    ok = arius.handle("프로젝트 생성 슈트")
    assert ok.source == "skill:project"
    assert "슈트" in ok.text


def test_user_admin_add_and_setrole():
    arius = make_arius()
    arius.login("owner")
    added = arius.handle("사용자 추가 newbie operator")
    assert added.source == "skill:user-admin"
    assert arius.permissions.get("newbie").role is Role.OPERATOR
    changed = arius.handle("권한 변경 newbie admin")
    assert changed.source == "skill:user-admin"
    assert arius.permissions.get("newbie").role is Role.ADMIN


def test_ensure_utf8_never_raises():
    from arius.cli import _ensure_utf8

    _ensure_utf8()  # must be a no-op or a successful reconfigure on any platform
    _ensure_utf8()  # idempotent
