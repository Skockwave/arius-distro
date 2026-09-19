import itertools
from array import array

from arius.mic import Microphone, Phrase, rms
from arius.voice import SpeechToText

QUIET = array("h", [10] * 1024).tobytes()
LOUD = array("h", [3000, -3000] * 512).tobytes()


def _fake(seq_blocks):
    seq = iter(seq_blocks)
    clock = [0.0]

    def factory():
        def read():
            clock[0] += 1024 / 16000
            return next(seq)
        return read, lambda: None

    return factory, (lambda: clock[0])


def test_rms_distinguishes_silence_from_speech():
    assert rms(QUIET) < 50 and rms(LOUD) > 2000
    assert rms(b"") == 0.0


def test_microphone_captures_one_phrase_with_preroll_and_silence_cut():
    factory, clock = _fake(itertools.chain([QUIET] * 12, [LOUD] * 8, [QUIET] * 30, itertools.repeat(QUIET)))
    mic = Microphone(stream_factory=factory, clock=clock)
    phrase = mic.listen(timeout=5)
    assert isinstance(phrase, Phrase)
    # 8 loud blocks + ~0.3s preroll + ~0.8s trailing silence ≈ 1.5s
    assert 1.2 < phrase.seconds < 2.0
    assert phrase.sample_rate == 16000 and phrase.sample_width == 2


def test_microphone_times_out_on_silence():
    factory, clock = _fake(itertools.repeat(QUIET))
    mic = Microphone(stream_factory=factory, clock=clock)
    assert mic.listen(timeout=2) is None


def test_stt_prefers_injected_sounddevice_microphone_and_reports_backend():
    class FakeMic:
        def listen(self, timeout, phrase_limit):
            return Phrase(LOUD * 4)

    stt = SpeechToText(microphone=FakeMic())
    if stt._recognizer is None:  # SpeechRecognition not installed here
        assert not stt.available and "SpeechRecognition" in (stt.reason or "")
        return
    assert stt.available and stt.mic_backend == "sounddevice"
    # recognition itself needs the network; swap it for a stub
    stt._recognizer.recognize_google = lambda audio, language: "아리우스 안녕"
    assert stt.listen() == "아리우스 안녕"
