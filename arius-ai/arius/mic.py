"""Microphone capture without PyAudio.

`sounddevice` ships prebuilt wheels with PortAudio bundled for every current
Python on Windows and macOS (Linux needs `libportaudio2`), so it installs
without a compiler — unlike PyAudio, which needs a wheel for the exact Python
version. This module records one spoken phrase using a simple energy-based
voice-activity detector and hands the PCM to SpeechRecognition.
"""

from __future__ import annotations

import time
from array import array
from collections.abc import Callable
from dataclasses import dataclass

SAMPLE_RATE = 16000
SAMPLE_WIDTH = 2  # int16
BLOCK = 1024  # frames per read (~64 ms)


@dataclass
class Phrase:
    pcm: bytes
    sample_rate: int = SAMPLE_RATE
    sample_width: int = SAMPLE_WIDTH

    @property
    def seconds(self) -> float:
        return len(self.pcm) / (self.sample_rate * self.sample_width)


def rms(block: bytes) -> float:
    samples = array("h")
    samples.frombytes(block[: len(block) - (len(block) % 2)])
    if not samples:
        return 0.0
    return (sum(s * s for s in samples) / len(samples)) ** 0.5


def sounddevice_available() -> tuple[bool, str]:
    try:
        import sounddevice  # type: ignore  # noqa: F401
    except ImportError:
        return False, "`pip install sounddevice` 가 필요합니다."
    except OSError as exc:  # PortAudio library missing (Linux)
        return False, f"PortAudio 를 찾지 못했습니다 ({exc.__class__.__name__}). Linux: `sudo apt install libportaudio2`"
    return True, ""


def list_input_devices(sd=None) -> list[str]:
    """Names of input-capable devices, in sounddevice index order (gaps for output-only devices are dropped)."""
    return [name for _idx, name in input_devices(sd)]


def input_devices(sd=None) -> list[tuple[int, str]]:
    """(index, name) of every device with an input channel."""
    try:
        if sd is None:
            import sounddevice as sd  # type: ignore
        out = []
        for idx, d in enumerate(sd.query_devices()):
            if d.get("max_input_channels", 0) > 0:
                out.append((idx, str(d.get("name", ""))))
        return out
    except Exception:
        return []


def default_input_device(sd=None) -> tuple[int, str] | None:
    try:
        if sd is None:
            import sounddevice as sd  # type: ignore
        idx = sd.default.device[0]
        if idx is None or idx < 0:
            return None
        return idx, str(sd.query_devices(idx).get("name", ""))
    except Exception:
        return None


def find_input_device(query: str | int | None, sd=None) -> tuple[int, str] | None:
    """Resolve a config value to (index, name): an index, or a case-insensitive substring of the
    device name ("이어폰", "Headset", "Realtek"). None/"" = the OS default input."""
    if query is None or query == "":
        return None
    devices = input_devices(sd)
    if isinstance(query, int) or str(query).strip().isdigit():
        idx = int(query)
        for i, name in devices:
            if i == idx:
                return i, name
        return None
    q = str(query).strip().lower()
    for i, name in devices:
        if q in name.lower():
            return i, name
    return None


def _default_stream_factory(device: int | None = None):
    import sounddevice as sd  # type: ignore

    stream = sd.RawInputStream(samplerate=SAMPLE_RATE, blocksize=BLOCK, channels=1, dtype="int16", device=device)
    stream.start()

    def read() -> bytes:
        data, _overflowed = stream.read(BLOCK)
        return bytes(data)

    return read, stream.stop


class Microphone:
    """Record one phrase: wait for speech (timeout), then stop after silence."""

    def __init__(
        self,
        *,
        stream_factory: Callable[[], tuple[Callable[[], bytes], Callable[[], None]]] | None = None,
        calibrate_seconds: float = 0.4,
        silence_seconds: float = 0.8,
        preroll_seconds: float = 0.3,
        min_threshold: float = 250.0,
        clock: Callable[[], float] = time.monotonic,
        device: int | None = None,
    ) -> None:
        self.device = device
        self._factory = stream_factory or (lambda: _default_stream_factory(device))
        self.calibrate_seconds = calibrate_seconds
        self.silence_seconds = silence_seconds
        self.preroll_seconds = preroll_seconds
        self.min_threshold = min_threshold
        self.clock = clock
        self.threshold = min_threshold

    def listen(self, timeout: float = 6.0, phrase_limit: float = 15.0) -> Phrase | None:
        read, close = self._factory()
        try:
            block_secs = BLOCK / SAMPLE_RATE
            # calibrate on ambient noise
            noise = []
            t0 = self.clock()
            while self.clock() - t0 < self.calibrate_seconds:
                noise.append(rms(read()))
            ambient = sum(noise) / len(noise) if noise else 0.0
            self.threshold = max(self.min_threshold, ambient * 3.0 + 150.0)

            # wait for speech
            preroll: list[bytes] = []
            keep = max(1, int(self.preroll_seconds / block_secs))
            started = self.clock()
            while True:
                block = read()
                preroll.append(block)
                if len(preroll) > keep:
                    preroll.pop(0)
                if rms(block) > self.threshold:
                    break
                if self.clock() - started > timeout:
                    return None

            # record until silence
            frames = list(preroll)
            silent_for = 0.0
            began = self.clock()
            while True:
                block = read()
                frames.append(block)
                if rms(block) > self.threshold:
                    silent_for = 0.0
                else:
                    silent_for += block_secs
                    if silent_for >= self.silence_seconds:
                        break
                if self.clock() - began > phrase_limit:
                    break
            return Phrase(b"".join(frames))
        finally:
            try:
                close()
            except Exception:
                pass
