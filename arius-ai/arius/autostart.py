"""Start ARIUS automatically at login.

  Windows  - a shortcut in the user's Startup folder (visible, minimized console,
             or hidden via pythonw.exe when hidden=True)
  macOS    - a LaunchAgent plist in ~/Library/LaunchAgents (RunAtLoad)
  Linux    - a .desktop entry in ~/.config/autostart

The entry runs `main.py agent --discord --listen`: heartbeat + Discord
conversation + wake-word voice, all in one process, logging to ~/.arius/agent.log.
Everything is per-user (no admin rights) and reversible with `disable`.
"""

from __future__ import annotations

import os
import platform
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

LABEL = "com.arius.agent"
DEFAULT_ARGS = ["agent", "--discord", "--listen"]
Runner = Callable[[list[str]], tuple[int, str]]


def _run(args: list[str]) -> tuple[int, str]:
    try:
        p = subprocess.run(args, capture_output=True, text=True, errors="replace", timeout=60)
    except (OSError, subprocess.SubprocessError) as exc:
        return 1, str(exc)
    return p.returncode, (p.stdout or "") + (p.stderr or "")


class Autostart:
    def __init__(
        self,
        project_dir: str | Path,
        *,
        system: str | None = None,
        home: str | Path | None = None,
        appdata: str | None = None,
        runner: Runner | None = None,
    ) -> None:
        self.project_dir = Path(project_dir).resolve()
        self.system = system or platform.system()
        self.home = Path(home or Path.home())
        self.appdata = appdata or os.environ.get("APPDATA", "")
        self.runner = runner or _run

    # -- locations ----------------------------------------------------------------
    def entry_path(self) -> Path:
        if self.system == "Windows":
            base = Path(self.appdata) if self.appdata else self.home / "AppData" / "Roaming"
            return base / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup" / "ARIUS.lnk"
        if self.system == "Darwin":
            return self.home / "Library" / "LaunchAgents" / f"{LABEL}.plist"
        return self.home / ".config" / "autostart" / "arius.desktop"

    def python(self, hidden: bool = False) -> str:
        venv = self.project_dir / (".venv/Scripts" if self.system == "Windows" else ".venv/bin")
        if self.system == "Windows":
            exe = venv / ("pythonw.exe" if hidden else "python.exe")
            if exe.exists():
                return str(exe)
            return "pythonw.exe" if hidden else "python.exe"
        exe = venv / "python"
        return str(exe) if exe.exists() else (sys.executable or "python3")

    # -- enable / disable ------------------------------------------------------------
    def enable(self, args: list[str] | None = None, hidden: bool = False) -> str:
        args = list(args or DEFAULT_ARGS)
        entry = self.entry_path()
        entry.parent.mkdir(parents=True, exist_ok=True)
        if self.system == "Windows":
            return self._enable_windows(entry, args, hidden)
        if self.system == "Darwin":
            return self._enable_macos(entry, args)
        return self._enable_linux(entry, args)

    def disable(self) -> str:
        entry = self.entry_path()
        if self.system == "Darwin" and entry.exists():
            self.runner(["launchctl", "unload", str(entry)])
        if entry.exists():
            entry.unlink()
            return f"자동 시작을 해제했습니다: {entry}"
        return "자동 시작이 등록되어 있지 않습니다."

    def status(self) -> str:
        entry = self.entry_path()
        return f"자동 시작: {'켜짐' if entry.exists() else '꺼짐'} ({entry})"

    # -- per-OS ---------------------------------------------------------------------------
    def _enable_windows(self, entry: Path, args: list[str], hidden: bool) -> str:
        if hidden:
            target = self.python(hidden=True)
            arguments = " ".join(['"main.py"', *args])
        else:
            target = str(self.project_dir / "run.bat")
            arguments = " ".join(args)
        ps = (
            "$ws = New-Object -ComObject WScript.Shell; "
            f"$s = $ws.CreateShortcut('{entry}'); "
            f"$s.TargetPath = '{target}'; "
            f"$s.Arguments = '{arguments}'; "
            f"$s.WorkingDirectory = '{self.project_dir}'; "
            f"$s.WindowStyle = {7 if not hidden else 1}; "
            "$s.Description = 'ARIUS 자동 시작'; $s.Save()"
        )
        code, out = self.runner(["powershell", "-NoProfile", "-Command", ps])
        if code != 0:
            return f"시작프로그램 등록 실패: {out.strip()[:300]}"
        how = "창 없이(백그라운드)" if hidden else "최소화된 창으로"
        return f"자동 시작을 등록했습니다 ({how}). 다음 로그인부터 ARIUS가 켜집니다.\n  {entry}"

    def _enable_macos(self, entry: Path, args: list[str]) -> str:
        log = self.home / ".arius" / "agent.log"
        log.parent.mkdir(parents=True, exist_ok=True)
        prog = "".join(f"\n        <string>{a}</string>" for a in [self.python(), "main.py", *args])
        plist = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key><string>{LABEL}</string>
    <key>ProgramArguments</key>
    <array>{prog}
    </array>
    <key>WorkingDirectory</key><string>{self.project_dir}</string>
    <key>RunAtLoad</key><true/>
    <key>KeepAlive</key><false/>
    <key>StandardOutPath</key><string>{log}</string>
    <key>StandardErrorPath</key><string>{log}</string>
    <key>EnvironmentVariables</key><dict><key>PYTHONUTF8</key><string>1</string></dict>
</dict>
</plist>
"""
        entry.write_text(plist, encoding="utf-8")
        self.runner(["launchctl", "unload", str(entry)])
        code, out = self.runner(["launchctl", "load", str(entry)])
        note = "" if code == 0 else f" (launchctl: {out.strip()[:120]} — 다음 로그인부터 적용)"
        return f"자동 시작을 등록했습니다 (LaunchAgent). 로그: {log}{note}\n  {entry}"

    def _enable_linux(self, entry: Path, args: list[str]) -> str:
        log = self.home / ".arius" / "agent.log"
        log.parent.mkdir(parents=True, exist_ok=True)
        cmd = f'bash -c \'cd "{self.project_dir}" && PYTHONUTF8=1 "{self.python()}" main.py {" ".join(args)} >> "{log}" 2>&1\''
        entry.write_text(
            "[Desktop Entry]\nType=Application\nName=ARIUS\nComment=로컬 AI 비서 자동 시작\n"
            f"Exec={cmd}\nTerminal=false\nX-GNOME-Autostart-enabled=true\n",
            encoding="utf-8",
        )
        return f"자동 시작을 등록했습니다 (autostart .desktop). 로그: {log}\n  {entry}"
