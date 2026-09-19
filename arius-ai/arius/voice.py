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

from arius.privacy import looks_secret, redact

_BULLETS = re.compile(r"^\s*[•\-\*▪◦]\s*", re.MULTILINE)
_PAREN_NOTE = re.compile(r"\((?:참고|알림)[^)]*\)")
_URL = re.compile(r"https?://\S+")


def speakable(text: str, limit: int = 400) -> str:
    """Turn a reply into something pleasant to hear: no bullets, notes, URLs — and no secrets."""
    t = redact(text) if looks_secret(text) else text
    t = _PAREN_NOTE.sub("", t)
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
        pyttsx3_note = ""
        try:
            import pyttsx3  # type: ignore
        except ImportError:
            pyttsx3 = None  # type: ignore
        if pyttsx3 is not None:
            try:
                engine = pyttsx3.init()
                engine.setProperty("rate", self.rate)
                if self.voice_name:
                    for v in engine.getProperty("voices") or []:
                        if self.voice_name.lower() in (getattr(v, "name", "") or "").lower():
                            engine.setProperty("voice", v.id)
                            break
                self._engine = engine
                return "pyttsx3"
            except Exception as exc:  # pragma: no cover - depends on host audio stack
                pyttsx3_note = f" (pyttsx3 는 설치됐지만 엔진 초기화 실패: {exc.__class__.__name__})"
        system = platform.system()
        if system == "Darwin" and shutil.which("say"):
            return "say"
        if system == "Windows" and (shutil.which("powershell") or shutil.which("pwsh")):
            return "powershell"
        for cmd in ("spd-say", "espeak-ng", "espeak"):
            if shutil.which(cmd):
                return cmd
        if platform.system() == "Linux":
            fix = "Linux 는 `sudo apt install espeak-ng` (또는 `speech-dispatcher`) 를 설치하면 됩니다."
        elif pyttsx3 is None:
            fix = "`pip install pyttsx3` 를 설치하면 OS 내장 음성을 사용합니다."
        else:
            fix = "OS 음성 설정에서 한국어 음성이 설치되어 있는지 확인하십시오."
        self.reason = f"사용 가능한 음성 엔진이 없습니다.{pyttsx3_note} {fix}"
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
    """Google Web Speech via SpeechRecognition. Microphone backends, in order:
    sounddevice (prebuilt wheels, no compiler) then PyAudio (sr.Microphone)."""

    def __init__(self, language: str = "ko-KR", timeout: float = 6.0, phrase_limit: float = 15.0, microphone=None) -> None:
        self.language = language
        self.timeout = timeout
        self.phrase_limit = phrase_limit
        self._sr = None
        self._recognizer = None
        self._mic = microphone  # injected sounddevice-style Microphone (tests) or None
        self.mic_backend: str | None = None
        self.reason: str | None = None
        try:
            import speech_recognition as sr  # type: ignore

            self._sr = sr
            self._recognizer = sr.Recognizer()
        except ImportError:
            self.reason = "음성 인식을 쓰려면 `pip install SpeechRecognition sounddevice` 가 필요합니다 (setup-voice 로 설치)."
            return
        if self._mic is not None:
            self.mic_backend = "sounddevice"
            return
        from arius.mic import Microphone, sounddevice_available

        ok, why = sounddevice_available()
        if ok:
            self._mic = Microphone()
            self.mic_backend = "sounddevice"
            return
        try:
            import pyaudio  # type: ignore  # noqa: F401

            self.mic_backend = "pyaudio"
        except ImportError:
            self.reason = f"마이크 라이브러리가 없습니다. {why} (setup-voice 로 설치)"

    @property
    def available(self) -> bool:
        return self._recognizer is not None and self.mic_backend is not None

    def listen(self) -> str | None:
        """Capture one utterance. None = nothing heard / unavailable, '' = unintelligible."""
        if not self.available:
            return None
        sr = self._sr
        if self.mic_backend == "sounddevice":
            try:
                phrase = self._mic.listen(timeout=self.timeout, phrase_limit=self.phrase_limit)
            except Exception as exc:
                self.reason = f"마이크를 열 수 없습니다: {exc} (마이크 연결과 OS 마이크 권한을 확인하십시오)"
                return None
            if phrase is None:
                return None
            audio = sr.AudioData(phrase.pcm, phrase.sample_rate, phrase.sample_width)
        else:
            try:
                with sr.Microphone() as source:
                    self._recognizer.adjust_for_ambient_noise(source, duration=0.4)
                    audio = self._recognizer.listen(source, timeout=self.timeout, phrase_time_limit=self.phrase_limit)
            except (OSError, AttributeError) as exc:
                self.reason = f"마이크를 열 수 없습니다: {exc} (마이크 연결과 OS 마이크 권한을 확인하십시오)"
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


# --- Wake-word conversation ---------------------------------------------------------

import threading as _threading
import time as _time
from collections.abc import Callable as _Callable

_STRIP = re.compile(r"[\s\.\,\!\?\~\-\_\'\"\(\)\[\]…·]+")


def _norm(text: str) -> str:
    return _STRIP.sub("", (text or "").lower())


class VoiceConversation:
    """Keep listening; answer when called by name, then stay awake for follow-ups."""

    def __init__(
        self,
        stt: SpeechToText,
        tts: TextToSpeech,
        respond: _Callable[[str], str],
        wake_words: list[str],
        *,
        awake_seconds: int = 20,
        on_event: _Callable[[str], None] | None = None,
        ack_phrase: str = "네, 말씀하세요.",
        unclear_phrase: str = "잘 듣지 못했습니다. 다시 말씀해 주시겠어요?",
    ) -> None:
        self.stt = stt
        self.tts = tts
        self.respond = respond
        self.wake_words = [w for w in wake_words if w]
        self.awake_seconds = max(0, int(awake_seconds))
        self.on_event = on_event or (lambda m: None)
        self.ack_phrase = ack_phrase
        self.unclear_phrase = unclear_phrase
        self._awake_until = 0.0

    def detect_wake(self, heard: str) -> tuple[bool, str]:
        """(called?, remaining text). Matching ignores spaces/punctuation, so
        '아리 우스' and '아리우스!' both count."""
        n = _norm(heard)
        for w in self.wake_words:
            wn = _norm(w)
            if wn and wn in n:
                remainder = re.sub(re.escape(w), " ", heard, flags=re.IGNORECASE)
                # also strip a spaced-out rendering of the name
                remainder = re.sub(r"\s*".join(map(re.escape, w)), " ", remainder, flags=re.IGNORECASE)
                return True, " ".join(remainder.split()).strip(" ,.!?~")
        return False, heard

    @property
    def awake(self) -> bool:
        return _time.monotonic() < self._awake_until

    def handle_unclear(self) -> str | None:
        """Speech was heard but not understood. While awake, ask to repeat instead of guessing."""
        if not self.awake:
            return None
        self._awake_until = _time.monotonic() + self.awake_seconds
        self.on_event("잘 듣지 못함 — 다시 요청")
        self.tts.speak(self.unclear_phrase)
        return self.unclear_phrase

    def handle_utterance(self, heard: str) -> str | None:
        """One transcript in → spoken reply (or None if it was not for us)."""
        called, query = self.detect_wake(heard)
        if not called and not self.awake:
            return None
        if called and not query:
            self._awake_until = _time.monotonic() + self.awake_seconds
            self.on_event("호출됨 — 대기 중")
            self.tts.speak(self.ack_phrase)
            return self.ack_phrase
        reply = self.respond(query or heard)
        self._awake_until = _time.monotonic() + self.awake_seconds
        self.on_event(f"나: {query or heard}")
        self.on_event(f"답: {reply[:80]}")
        self.tts.speak(reply)
        return reply

    def run(self, stop_event: _threading.Event | None = None) -> None:
        stop_event = stop_event or _threading.Event()
        self.on_event(f"듣는 중… '{', '.join(self.wake_words)}' 라고 부르면 대답합니다. (Ctrl+C 로 종료)")
        while not stop_event.is_set():
            heard = self.stt.listen()
            if heard is None:
                if self.stt.reason and "마이크" in self.stt.reason:
                    self.on_event(self.stt.reason)
                    return
                continue
            if not heard:
                self.handle_unclear()
                continue
            try:
                self.handle_utterance(heard)
            except Exception as exc:  # keep listening whatever happens
                self.on_event(f"응답 오류: {exc}")
