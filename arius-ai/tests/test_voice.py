from arius.voice import SpeechToText, TextToSpeech, speakable


def test_speakable_strips_noise_for_listening():
    raw = "학습 완료: 제목\n  • 출처: https://x.y/z\n  • 요약: 본문 (참고: 오프라인 모드입니다) 끝"
    out = speakable(raw)
    assert "https://" not in out
    assert "•" not in out
    assert "(참고" not in out
    assert "본문" in out and "끝" in out


def test_speakable_truncates_long_text():
    out = speakable("가" * 1000, limit=100)
    assert len(out) == 100
    assert out.endswith("…")


def test_tts_disabled_backend_never_speaks_and_never_raises():
    tts = TextToSpeech(backend=None)
    assert tts.available is False
    assert tts.speak("안녕하십니까") is False


def test_tts_auto_detection_does_not_crash_without_engines():
    tts = TextToSpeech()  # whatever the host has (or nothing)
    if not tts.available:
        assert tts.reason  # a helpful message is provided


def test_stt_unavailable_is_reported_not_raised():
    stt = SpeechToText()
    if not stt.available:
        assert stt.reason
        assert stt.listen() is None
