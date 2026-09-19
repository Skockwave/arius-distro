import tempfile
from pathlib import Path

from arius.autostart import DEFAULT_ARGS, Autostart


def _auto(system, calls):
    home = Path(tempfile.mkdtemp())
    return Autostart("/opt/ARIUS", system=system, home=home,
                     appdata=str(home / "AppData" / "Roaming"),
                     runner=lambda a: calls.append(a) or (0, "")), home


def test_windows_creates_startup_shortcut_via_powershell():
    calls = []
    auto, home = _auto("Windows", calls)
    msg = auto.enable()
    assert "등록했습니다" in msg
    assert auto.entry_path().name == "ARIUS.lnk" and "Startup" in str(auto.entry_path())
    ps = " ".join(calls[-1])
    assert calls[-1][0] == "powershell" and "run.bat" in ps and "agent --discord --listen" in ps and "WindowStyle = 7" in ps
    hidden = auto.enable(hidden=True)
    assert "백그라운드" in hidden and "pythonw" in " ".join(calls[-1])


def test_macos_writes_launchagent_and_loads_it():
    calls = []
    auto, home = _auto("Darwin", calls)
    msg = auto.enable(["agent"])
    plist = auto.entry_path()
    assert plist.exists() and plist.name == "com.arius.agent.plist"
    text = plist.read_text(encoding="utf-8")
    assert "<string>main.py</string>" in text and "<string>agent</string>" in text and "RunAtLoad" in text
    assert any(c[:2] == ["launchctl", "load"] for c in calls)
    assert "켜짐" in auto.status()
    assert "해제" in auto.disable() and not plist.exists()
    assert any(c[:2] == ["launchctl", "unload"] for c in calls)


def test_linux_writes_desktop_entry_with_log_redirect():
    calls = []
    auto, home = _auto("Linux", calls)
    auto.enable()
    entry = auto.entry_path()
    assert entry.exists() and entry.suffix == ".desktop"
    text = entry.read_text(encoding="utf-8")
    assert "[Desktop Entry]" in text and "main.py agent --discord --listen" in text and "agent.log" in text
    assert "자동 시작이 등록되어 있지 않습니다" in Autostart("/x", system="Linux", home=Path(tempfile.mkdtemp())).disable()


def test_default_args_cover_everything_always_on():
    assert DEFAULT_ARGS == ["agent", "--discord", "--listen"]


def test_cli_parses_autostart_and_agent_listen():
    from arius.cli import build_parser

    p = build_parser()
    a = p.parse_args(["autostart", "enable", "--hidden", "--no-discord"])
    assert a.action == "enable" and a.hidden and a.no_discord and not a.no_listen
    b = p.parse_args(["agent", "--discord", "--listen"])
    assert b.discord and b.listen
