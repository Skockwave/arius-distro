"""One-command installation and diagnosis of optional features (voice first).

`python main.py setup voice` installs SpeechRecognition + PyAudio + pyttsx3
into the *current* interpreter (so the .venv when launched via run.bat/run.sh),
then checks imports and lists microphones. PyAudio needs the PortAudio C
library: Windows gets prebuilt wheels from PyPI, macOS needs `brew install
portaudio`, Debian/Ubuntu need `portaudio19-dev` — the report says exactly
which step is missing instead of dumping a compiler error.
"""

from __future__ import annotations

import importlib
import platform
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass, field

VOICE_PACKAGES = ["SpeechRecognition", "pyttsx3", "pyaudio"]


@dataclass
class StepResult:
    name: str
    ok: bool
    detail: str = ""


@dataclass
class SetupReport:
    steps: list[StepResult] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return all(s.ok for s in self.steps)

    def render(self) -> str:
        lines = [f"{'✅' if s.ok else '❌'} {s.name}" + (f" — {s.detail}" if s.detail else "") for s in self.steps]
        return "\n".join(lines)


Runner = Callable[[list[str]], tuple[int, str]]


def _default_runner(args: list[str]) -> tuple[int, str]:
    try:
        proc = subprocess.run(args, capture_output=True, text=True, errors="replace", timeout=900)
    except (OSError, subprocess.SubprocessError) as exc:
        return 1, str(exc)
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


def portaudio_hint() -> str:
    sysname = platform.system()
    if sysname == "Darwin":
        return "터미널에서 `brew install portaudio` 를 먼저 실행한 뒤 다시 시도하십시오."
    if sysname == "Linux":
        return ("PortAudio 개발 패키지가 필요합니다: Ubuntu/Debian `sudo apt install portaudio19-dev python3-dev`, "
                "Fedora `sudo dnf install portaudio-devel`, 그다음 다시 시도하십시오.")
    if sysname == "Windows":
        return ("이 Python 버전용 PyAudio 휠이 없을 수 있습니다. Python 3.10~3.13 은 `pip install pyaudio` 로 보통 설치됩니다. "
                "그래도 실패하면 `pip install pipwin && pipwin install pyaudio` 를 시도하십시오.")
    return "PortAudio 라이브러리를 설치한 뒤 다시 시도하십시오."


def pip_install(packages: list[str], runner: Runner | None = None, python: str | None = None) -> StepResult:
    runner = runner or _default_runner
    python = python or sys.executable
    code, out = runner([python, "-m", "pip", "install", "--disable-pip-version-check", *packages])
    if code == 0:
        return StepResult(f"pip install {' '.join(packages)}", True)
    low = out.lower()
    if "portaudio" in low or "pyaudio" in low and ("gcc" in low or "wheel" in low or "build" in low):
        return StepResult(f"pip install {' '.join(packages)}", False, "PyAudio 빌드 실패 — " + portaudio_hint())
    if "no matching distribution" in low or "could not find a version" in low:
        return StepResult(f"pip install {' '.join(packages)}", False, "이 Python 버전용 패키지를 찾지 못했습니다. " + portaudio_hint())
    if "network" in low or "connection" in low or "timed out" in low or "temporary failure" in low:
        return StepResult(f"pip install {' '.join(packages)}", False, "네트워크 오류 — 인터넷 연결을 확인하십시오.")
    tail = " ".join(out.strip().splitlines()[-3:])[:300]
    return StepResult(f"pip install {' '.join(packages)}", False, tail or f"종료 코드 {code}")


def check_import(module: str, label: str | None = None) -> StepResult:
    try:
        importlib.import_module(module)
        return StepResult(label or module, True)
    except Exception as exc:  # ImportError or a broken native module
        return StepResult(label or module, False, f"{exc.__class__.__name__}: {str(exc)[:120]}")


def check_microphones() -> StepResult:
    try:
        import speech_recognition as sr  # type: ignore

        names = sr.Microphone.list_microphone_names()
    except Exception as exc:
        return StepResult("마이크 목록", False, f"{exc.__class__.__name__}: {str(exc)[:120]} (PyAudio 필요)")
    if not names:
        return StepResult("마이크 목록", False, "마이크 장치를 찾지 못했습니다. 이어폰/헤드셋 연결과 OS 마이크 권한을 확인하십시오.")
    shown = ", ".join(n for n in names[:5] if n)
    return StepResult("마이크 목록", True, f"{len(names)}개 — {shown}")


def check_tts() -> StepResult:
    from arius.voice import TextToSpeech

    tts = TextToSpeech()
    return StepResult("음성 출력(TTS)", tts.available, f"엔진: {tts.backend}" if tts.available else (tts.reason or ""))


def check_voice() -> SetupReport:
    rep = SetupReport()
    rep.steps.append(check_import("speech_recognition", "음성 인식 라이브러리 (SpeechRecognition)"))
    pa = check_import("pyaudio", "마이크 입력 라이브러리 (PyAudio)")
    if not pa.ok:
        pa.detail = (pa.detail + " — " if pa.detail else "") + portaudio_hint()
    rep.steps.append(pa)
    rep.steps.append(check_import("pyttsx3", "음성 합성 라이브러리 (pyttsx3)"))
    rep.steps.append(check_tts())
    if pa.ok:
        rep.steps.append(check_microphones())
    return rep


def install_voice(runner: Runner | None = None, python: str | None = None) -> SetupReport:
    rep = SetupReport()
    # pure-Python packages first so a PyAudio build failure never blocks them
    rep.steps.append(pip_install(["SpeechRecognition", "pyttsx3"], runner, python))
    rep.steps.append(pip_install(["pyaudio"], runner, python))
    rep.steps.extend(check_voice().steps)
    return rep
