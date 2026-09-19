"""Voice I/O for ARIUS: text-to-speech and speech-to-text.

Everything here is optional and degrades gracefully — the assistant never
crashes because a microphone or audio library is missing.

Text-to-speech backends, tried in order:
  1. pyttsx3           (pip install pyttsx3)  — offline, uses OS voices
  2. OS-native CLI      macOS `say`, Windows PowerShell System.Speech,
                        Linux `spd-say` / `espeak-ng` / `espeak`
  3. none               speak() returns False and the caller just prints

Speech-to-text:
  * SpeechRecognition + PyAudio  (pip install SpeechRecognition pyaudio)
    using the free Google Web Speech API (supports ko-KR). Offline STT
    (Vosk / Whisper) can be plugged in the same way.
"""

from __future__ import annotations

import platform
import re
import shutil
import subprocess

_BULLETS = re.compile(r"^\s*[•\-\*▪◦]\s*", re.MULTILINE)
_PAREN_NOTE = re.compile(r"\((?:참고|알림)[^)]*\)")
_URL = re.compile(r"https?://\S+")


def speakable(text: str, limit: int = 400) -> str:
    """Turn a reply into something pleasant to hear: no bullets, notes, URLs."""
    t = _PAREN_NOTE.sub("", text)
    t = _URL.sub("링크", t)
    t = _BULLETS.sub("", t)
    t = re.sub(r"[`*_#>|]", "", t)
    t = " ".join(t.split())
    return t if len(t) <= limit else t[: limit - 1] + "…"


class TextToSpeech:
    def __init__(
        self,
        language: str = "ko-KR",
        rate: int = 180,
        voice_name: str = "",
        backend: str | None = "auto",
    ) -> None:
        self.language = language
        self.rate = rate
        self.voice_name = voice_name
        self._engine = None
        self.backend: str | None = None
        self.reason: str | None = None
        if backend == "auto":
            self.backend = self._pick()
        elif backend in (None, "none"):
            self.reason = "음성 출력이 비활성화되어 있습니다."
        else:
            self.backend = backend

    # -- detection -----------------------------------------------------------
    def _pick(self) -> str | None:
        try:
            import pyttsx3  # type: ignore

            engine = pyttsx3.init()
            engine.setProperty("rate", self.rate)
            if self.voice_name:
                for v in engine.getProperty("voices") or []:
                    if self.voice_name.lower() in (getattr(v, "name", "") or "").lower():
                        engine.setProperty("voice", v.id)
                        break
            self._engine = engine
            return "pyttsx3"
        except Exception:  # pragma: no cover - depends on host audio stack
            pass
        system = platform.system()
        if system == "Darwin" and shutil.which("say"):
            return "say"
        if system == "Windows" and (shutil.which("powershell") or shutil.which("pwsh")):
            return "powershell"
        for cmd in ("spd-say", "espeak-ng", "espeak"):
            if shutil.which(cmd):
                return cmd
        self.reason = (
            "사용 가능한 음성 엔진이 없습니다. `pip install pyttsx3` 또는 OS 음성 도구"
            "(macOS say / Linux espeak-ng)를 설치하십시오."
        )
        return None

    @property
    def available(self) -> bool:
        return self.backend is not None

    # -- speaking ------------------------------------------------------------
    def speak(self, text: str) -> bool:
        """Speak the text. Returns False if nothing could be spoken."""
        if not self.available:
            return False
        phrase = speakable(text)
        if not phrase:
            return False
        try:
            if self.backend == "pyttsx3" and self._engine is not None:
                self._engine.say(phrase)
                self._engine.runAndWait()
                return True
            if self.backend == "say":
                args = ["say", "-r", str(self.rate)]
                if self.voice_name:
                    args += ["-v", self.voice_name]
                subprocess.run(args, input=phrase, text=True, check=False, timeout=60)
                return True
            if self.backend == "powershell":
                exe = shutil.which("powershell") or shutil.which("pwsh") or "powershell"
                script = (
                    "[Console]::InputEncoding=[System.Text.Encoding]::UTF8;"
                    "Add-Type -AssemblyName System.Speech;"
                    "$s=New-Object System.Speech.Synthesis.SpeechSynthesizer;"
                    "$s.Speak([Console]::In.ReadToEnd())"
                )
                subprocess.run([exe, "-NoProfile", "-Command", script], input=phrase, text=True,
                               encoding="utf-8", check=False, timeout=60)
                return True
            if self.backend == "spd-say":
                subprocess.run(["spd-say", "-l", self.language.split("-")[0], "-w", phrase], check=False, timeout=60)
                return True
            if self.backend in ("espeak-ng", "espeak"):
                subprocess.run([self.backend, "-v", self.language.split("-")[0], "--stdin"],
                               input=phrase, text=True, check=False, timeout=60)
                return True
        except Exception as exc:  # pragma: no cover - host dependent
            self.reason = f"음성 출력 실패: {exc}"
            return False
        return False


class SpeechToText:
    def __init__(self, language: str = "ko-KR", timeout: float = 6.0, phrase_limit: float = 15.0) -> None:
        self.language = language
        self.timeout = timeout
        self.phrase_limit = phrase_limit
        self._sr = None
        self._recognizer = None
        self.reason: str | None = None
        try:
            import speech_recognition as sr  # type: ignore

            self._sr = sr
            self._recognizer = sr.Recognizer()
        except ImportError:
            self.reason = (
                "음성 인식을 쓰려면 `pip install SpeechRecognition pyaudio` 가 필요합니다."
            )

    @property
    def available(self) -> bool:
        return self._recognizer is not None

    def listen(self) -> str | None:
        """Capture one utterance. None = nothing heard / unavailable, '' = unintelligible."""
        if not self.available:
            return None
        sr = self._sr
        try:
            with sr.Microphone() as source:
                self._recognizer.adjust_for_ambient_noise(source, duration=0.4)
                audio = self._recognizer.listen(source, timeout=self.timeout, phrase_time_limit=self.phrase_limit)
        except (OSError, AttributeError) as exc:
            self.reason = f"마이크를 열 수 없습니다: {exc} (PyAudio 설치 및 마이크 권한을 확인하십시오)"
            return None
        except sr.WaitTimeoutError:
            return None
        try:
            return self._recognizer.recognize_google(audio, language=self.language)
        except sr.UnknownValueError:
            return ""
        except sr.RequestError as exc:
            self.reason = f"음성 인식 서비스 오류: {exc}"
            return None
