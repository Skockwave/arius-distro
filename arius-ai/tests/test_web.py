from arius.config import AriusConfig, UserConfig
from arius.core import Arius
from arius.memory import Memory
from arius.skills import SkillRegistry
from arius.skills.builtin import (
    WebLearnSkill,
    default_skills,
)
from arius.web import WebPage, _html_to_page, extract_first_url


def test_html_to_text_strips_scripts_and_keeps_body():
    html = """
    <html><head><title>테스트 페이지</title><style>.x{}</style></head>
    <body><script>var a=1;</script>
    <h1>제목</h1><p>첫 문단입니다.</p><p>두 번째 문단.</p></body></html>
    """
    page = _html_to_page("https://example.com", html)
    assert page.title == "테스트 페이지"
    assert "첫 문단입니다." in page.text
    assert "두 번째 문단." in page.text
    assert "var a=1" not in page.text  # script content dropped


def test_extract_first_url():
    assert extract_first_url("여기 봐 https://foo.bar/a?b=1 끝") == "https://foo.bar/a?b=1"
    assert extract_first_url("링크 없음") is None


def _fake_fetch(url, backend):
    return WebPage(
        url=url,
        title="포지 설치 안내",
        text="Minecraft Forge 1.20.1 설치 방법. 설치 프로그램을 실행하고 install client를 누릅니다.",
    )


def make_arius_with_web(role: str = "operator") -> Arius:
    config = AriusConfig(users=[UserConfig(username="op", role=role, display_name="운영자")])
    # registry with an injected fake fetcher so tests never hit the network
    skills = [s for s in default_skills() if not isinstance(s, WebLearnSkill)]
    skills.append(WebLearnSkill(fetcher=_fake_fetch))
    return Arius(config, memory=Memory(":memory:"), registry=SkillRegistry(skills))


def test_operator_can_learn_and_recall_web():
    arius = make_arius_with_web("operator")
    arius.login("op")
    learned = arius.handle("학습해: https://docs.example.com/forge")
    assert learned.source == "skill:web-learn"
    assert "학습 완료" in learned.text

    recalled = arius.handle("웹에서 포지 설치 찾아줘")
    assert recalled.source == "skill:web-recall"
    assert "포지 설치 안내" in recalled.text


def test_learn_requires_url():
    arius = make_arius_with_web("operator")
    arius.login("op")
    r = arius.handle("학습해: 그냥 아무거나")
    assert r.source == "skill:web-learn"
    assert "URL" in r.text or "주소" in r.text


def test_guest_cannot_web_learn():
    config = AriusConfig(users=[UserConfig(username="g", role="guest")])
    skills = [s for s in default_skills() if not isinstance(s, WebLearnSkill)]
    skills.append(WebLearnSkill(fetcher=_fake_fetch))
    arius = Arius(config, memory=Memory(":memory:"), registry=SkillRegistry(skills))
    arius.login("g")
    r = arius.handle("학습해: https://example.com")
    assert r.source.startswith("denied:")


def test_user_can_recall_but_not_learn():
    arius = make_arius_with_web("user")
    arius.login("op")  # 'op' user has role 'user' here
    denied = arius.handle("학습해: https://example.com")
    assert denied.source.startswith("denied:")
    # recall is allowed for users (web.read), even with nothing stored yet
    allowed = arius.handle("웹에서 뭐 배운 것 있어?")
    assert allowed.source == "skill:web-recall"


def test_chrome_backend_selected_by_keyword():
    seen = {}

    def spy_fetch(url, backend):
        seen["backend"] = backend
        return WebPage(url=url, title="t", text="본문")

    reg = SkillRegistry([WebLearnSkill(fetcher=spy_fetch)])
    config = AriusConfig(users=[UserConfig(username="op", role="operator")])
    arius = Arius(config, memory=Memory(":memory:"), registry=reg)
    arius.login("op")
    arius.handle("크롬으로 학습해: https://example.com")
    assert seen["backend"] == "chrome"
