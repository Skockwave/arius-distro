"""PC control: open things, launch and close programs, switch windows.

Everything is best-effort and OS-aware (Windows first, macOS/Linux where the
same idea exists). Nothing here deletes, installs or changes settings; the
riskiest action is closing a program, which the callers always confirm first
and which refuses protected processes (the server JVM, the shell, this app).

All shell interaction goes through an injectable ``run``/``popen`` so tests can
observe what would be executed without touching the host.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import webbrowser
from pathlib import Path
from urllib.parse import urlparse

# Built-in names people say out loud → what to run. Config desktop.programs extends/overrides.
BUILTIN_PROGRAMS: dict[str, dict[str, str]] = {
    "win32": {
        "메모장": "notepad", "notepad": "notepad", "계산기": "calc", "그림판": "mspaint", "탐색기": "explorer",
        "파일 탐색기": "explorer", "터미널": "start cmd", "명령 프롬프트": "start cmd", "파워셸": "start powershell",
        "크롬": "start chrome", "chrome": "start chrome", "엣지": "start msedge", "edge": "start msedge",
        "작업 관리자": "taskmgr", "설정": "start ms-settings:", "디스코드": "start discord://",
        "스팀": "start steam://open/main", "마인크래프트": "start minecraft:",
    },
    "darwin": {
        "메모장": 'open -a "TextEdit"', "계산기": 'open -a "Calculator"', "탐색기": "open .", "파인더": "open .",
        "터미널": 'open -a "Terminal"', "크롬": 'open -a "Google Chrome"', "사파리": 'open -a "Safari"',
        "디스코드": 'open -a "Discord"',
    },
    "linux": {
        "터미널": "x-terminal-emulator", "크롬": "google-chrome", "파이어폭스": "firefox", "탐색기": "xdg-open .",
    },
}

# Sites people ask for by name. Config desktop.sites extends/overrides.
BUILTIN_SITES: dict[str, str] = {
    "유튜브": "https://www.youtube.com", "youtube": "https://www.youtube.com",
    "구글": "https://www.google.com", "google": "https://www.google.com",
    "네이버": "https://www.naver.com", "naver": "https://www.naver.com",
    "깃허브": "https://github.com", "github": "https://github.com",
    "디스코드 웹": "https://discord.com/app", "지메일": "https://mail.google.com",
    "치지직": "https://chzzk.naver.com", "트위치": "https://www.twitch.tv",
    "마인크래프트 위키": "https://minecraft.wiki", "스피곳": "https://www.spigotmc.org",
    "페이퍼": "https://papermc.io", "커스포지": "https://www.curseforge.com/minecraft",
}

# Folder names people say → home subfolders (checked in order; OneDrive layouts too).
KNOWN_FOLDERS: dict[str, tuple[str, ...]] = {
    "다운로드": ("Downloads",), "다운로드 폴더": ("Downloads",), "downloads": ("Downloads",),
    "문서": ("Documents", "OneDrive/Documents", "OneDrive/문서"), "문서 폴더": ("Documents", "OneDrive/Documents"),
    "바탕화면": ("Desktop", "OneDrive/Desktop", "OneDrive/바탕 화면"), "바탕 화면": ("Desktop", "OneDrive/Desktop", "OneDrive/바탕 화면"),
    "사진": ("Pictures", "OneDrive/Pictures"), "음악": ("Music",), "동영상": ("Videos",), "비디오": ("Videos",),
    "홈": ("",), "내 폴더": ("",),
}


def _platform() -> str:
    return "win32" if sys.platform == "win32" else ("darwin" if sys.platform == "darwin" else "linux")


def _default_run(args, **kw):
    return subprocess.run(args, capture_output=True, text=True, errors="replace", timeout=kw.pop("timeout", 15), **kw)


def _default_popen(cmd: str, cwd: str | None = None) -> None:
    if sys.platform == "win32":
        subprocess.Popen(cmd, shell=True, cwd=cwd, creationflags=getattr(subprocess, "DETACHED_PROCESS", 0))
    else:
        subprocess.Popen(cmd, shell=True, cwd=cwd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)


class Desktop:
    def __init__(
        self,
        programs: dict[str, str] | None = None,
        sites: dict[str, str] | None = None,
        folders: dict[str, str] | None = None,
        *,
        allow_any_url: bool = True,
        protected: list[str] | None = None,
        home: str | os.PathLike[str] | None = None,
        platform: str | None = None,
        run=None,
        popen=None,
        browser=None,
        opener=None,
    ) -> None:
        self.platform = platform or _platform()
        self.programs = {**BUILTIN_PROGRAMS.get(self.platform, {}), **{k.lower(): v for k, v in (programs or {}).items()}}
        self.sites = {**BUILTIN_SITES, **{k.lower(): v for k, v in (sites or {}).items()}}
        self.folders = {k.lower(): v for k, v in (folders or {}).items()}
        self.allow_any_url = allow_any_url
        self.protected = [p.lower() for p in (protected or [])]
        self.home = Path(home) if home else Path.home()
        self._run = run or _default_run
        self._popen = popen or _default_popen
        self._browser = browser or webbrowser.open
        self._opener = opener  # (path) -> None; default: OS "open this"

    # -- resolution ---------------------------------------------------------------
    def resolve_folder(self, name: str) -> Path | None:
        key = name.strip().lower()
        if key in self.folders:
            return Path(os.path.expanduser(self.folders[key]))
        for sub in KNOWN_FOLDERS.get(key, ()):
            cand = self.home / sub if sub else self.home
            if cand.exists():
                return cand
        if key in KNOWN_FOLDERS:  # known name but folder missing: still return the primary guess
            return self.home / KNOWN_FOLDERS[key][0]
        return None

    def resolve_site(self, name: str) -> str | None:
        key = name.strip().lower()
        if key in self.sites:
            return self.sites[key]
        if is_url(name):
            url = name.strip() if "://" in name else "https://" + name.strip()
            if self.allow_any_url or _host(url) in {_host(u) for u in self.sites.values()}:
                return url
        return None

    def resolve_program(self, name: str) -> str | None:
        return self.programs.get(name.strip().lower())

    # -- actions ------------------------------------------------------------------
    def open_url(self, target: str) -> str:
        url = self.resolve_site(target)
        if not url:
            if is_url(target):
                return "실행하지 않았습니다.\n이유: 허용되지 않은 웹사이트입니다.\n다음 조치: config desktop.sites 에 등록하거나 desktop.allow_any_url 을 true 로 두세요."
            return f"실행하지 않았습니다.\n이유: '{target}' 은(는) 등록된 사이트가 아닙니다.\n다음 조치: 주소(URL)를 직접 말하거나 config desktop.sites 에 등록해 주세요."
        try:
            ok = self._browser(url)
        except Exception as exc:
            return f"실행하지 않았습니다.\n이유: 브라우저를 열 수 없습니다 ({exc}).\n다음 조치: 기본 브라우저 설정을 확인해 주세요."
        return f"완료했습니다. 브라우저에서 열었습니다: {url}" if ok is not False else "실행하지 않았습니다.\n이유: 브라우저가 응답하지 않았습니다.\n다음 조치: 기본 브라우저 설정을 확인해 주세요."

    def open_path(self, target: str) -> str:
        folder = self.resolve_folder(target)
        path = folder if folder is not None else Path(os.path.expanduser(target.strip().strip('"')))
        if not path.exists():
            return f"실행하지 않았습니다.\n이유: 경로가 없습니다: {path}\n다음 조치: 정확한 경로나 등록된 폴더 이름(다운로드, 문서, 바탕화면…)을 말해 주세요."
        try:
            if self._opener is not None:
                self._opener(str(path))
            elif self.platform == "win32":
                os.startfile(str(path))  # type: ignore[attr-defined]
            elif self.platform == "darwin":
                self._popen(f'open "{path}"')
            else:
                self._popen(f'xdg-open "{path}"')
        except Exception as exc:
            return f"실행하지 않았습니다.\n이유: 열 수 없습니다 ({exc}).\n다음 조치: 파일이 다른 프로그램에서 잠겨 있지 않은지 확인해 주세요."
        kind = "폴더" if path.is_dir() else "파일"
        return f"완료했습니다. {kind}를 열었습니다: {path}"

    def launch(self, name: str) -> str:
        cmd = self.resolve_program(name)
        if not cmd:
            known = ", ".join(sorted(self.programs)[:12])
            return (
                f"실행하지 않았습니다.\n이유: '{name}' 은(는) 등록된 프로그램이 아닙니다.\n"
                f"다음 조치: config desktop.programs 에 이름과 실행 경로를 등록해 주세요. (등록됨: {known})"
            )
        try:
            self._popen(cmd)
        except Exception as exc:
            return f"실행하지 않았습니다.\n이유: 실행 실패 ({exc}).\n다음 조치: 실행 경로가 맞는지 확인해 주세요."
        return f"완료했습니다. '{name}' 을(를) 실행했습니다."

    def running(self, limit: int = 15) -> str:
        from arius import sysinfo

        procs = sysinfo.top_processes(limit)
        if not procs:
            return "실행 중인 프로그램 목록을 가져오지 못했습니다."
        return "실행 중인 프로그램(메모리 순):\n" + "\n".join(f"  • {p['name']} (PID {p['pid']}, {p['mem_mb']:.0f}MB)" for p in procs)

    def is_protected(self, name: str) -> bool:
        base = Path(name.strip().strip('"')).stem.lower()
        return any(base == p or base.startswith(p) for p in self.protected)

    def close(self, name: str, force: bool = False) -> str:
        """Close a program by executable/name. Callers must confirm before calling this."""
        target = name.strip().strip('"')
        if not target:
            return "종료할 프로그램 이름이 비어 있습니다."
        if self.is_protected(target):
            return f"실행하지 않았습니다.\n이유: '{target}' 은(는) 보호된 프로세스입니다(서버·시스템·이 비서).\n다음 조치: 서버는 '서버 중지 확인' 으로, 시스템 프로세스는 직접 관리해 주세요."
        try:
            if self.platform == "win32":
                image = target if target.lower().endswith(".exe") else target + ".exe"
                args = ["taskkill", "/IM", image] + (["/F"] if force else [])
                res = self._run(args)
            elif self.platform == "darwin":
                res = self._run(["osascript", "-e", f'tell application "{target}" to quit'])
                if getattr(res, "returncode", 1) != 0:
                    res = self._run(["pkill", "-x" if not force else "-9", target])
            else:
                res = self._run(["pkill"] + (["-9"] if force else []) + ["-x", target])
        except Exception as exc:
            return f"실행하지 않았습니다.\n이유: 종료 명령 실패 ({exc}).\n다음 조치: 프로그램 이름(실행 파일명)을 확인해 주세요."
        out = ((getattr(res, "stdout", "") or "") + (getattr(res, "stderr", "") or "")).strip()
        if getattr(res, "returncode", 1) != 0:
            return f"실행하지 않았습니다.\n이유: '{target}' 을(를) 찾지 못했거나 종료를 거부했습니다. {out[:160]}\n다음 조치: '실행 중인 프로그램' 으로 정확한 이름을 확인해 주세요."
        return f"완료했습니다. '{target}' 을(를) 종료했습니다." + (f" {out[:120]}" if out else "")

    def switch_window(self, title: str) -> str:
        title = title.strip().strip('"')
        if not title:
            return "전환할 창 제목이 비어 있습니다."
        try:
            if self.platform == "win32":
                exe = shutil.which("powershell") or "powershell"
                safe = title.replace("'", "''")
                res = self._run([exe, "-NoProfile", "-Command", f"(New-Object -ComObject WScript.Shell).AppActivate('{safe}')"])
                ok = "True" in (getattr(res, "stdout", "") or "")
            elif self.platform == "darwin":
                res = self._run(["osascript", "-e", f'tell application "{title}" to activate'])
                ok = getattr(res, "returncode", 1) == 0
            else:
                if not shutil.which("wmctrl"):
                    return "실행하지 않았습니다.\n이유: 창 전환에는 wmctrl 이 필요합니다.\n다음 조치: `sudo apt install wmctrl`"
                res = self._run(["wmctrl", "-a", title])
                ok = getattr(res, "returncode", 1) == 0
        except Exception as exc:
            return f"실행하지 않았습니다.\n이유: 창 전환 실패 ({exc}).\n다음 조치: 창 제목의 일부를 정확히 말해 주세요."
        return f"완료했습니다. '{title}' 창으로 전환했습니다." if ok else f"실행하지 않았습니다.\n이유: '{title}' 창을 찾지 못했습니다.\n다음 조치: 창 제목의 앞부분을 정확히 말해 주세요."


def is_url(text: str) -> bool:
    t = (text or "").strip()
    if "://" in t:
        return urlparse(t).scheme in ("http", "https")
    return bool(t) and " " not in t and "." in t and not t.startswith(".") and not Path(t).exists() and t.rsplit(".", 1)[-1].isalpha()


def _host(url: str) -> str:
    return (urlparse(url).hostname or "").lower().removeprefix("www.")
