from arius.setup import SetupReport, StepResult, check_voice, install_voice, pip_install, portaudio_hint


def test_pip_install_success_and_failure_diagnosis():
    ok = pip_install(["SpeechRecognition"], runner=lambda args: (0, "Successfully installed"))
    assert ok.ok and "SpeechRecognition" in ok.name

    build_fail = pip_install(["pyaudio"], runner=lambda args: (1, "Building wheel for pyaudio ... error: portaudio.h: No such file"))
    assert not build_fail.ok and "PyAudio 빌드 실패" in build_fail.detail and portaudio_hint() in build_fail.detail

    no_dist = pip_install(["pyaudio"], runner=lambda args: (1, "ERROR: No matching distribution found for pyaudio"))
    assert not no_dist.ok and "찾지 못했습니다" in no_dist.detail

    net = pip_install(["x"], runner=lambda args: (1, "ReadTimeoutError: connection timed out"))
    assert not net.ok and "네트워크" in net.detail


def test_pip_install_uses_given_interpreter():
    seen = []
    pip_install(["pyttsx3"], runner=lambda args: seen.append(args) or (0, ""), python="/venv/bin/python")
    assert seen[0][:3] == ["/venv/bin/python", "-m", "pip"] and "pyttsx3" in seen[0]


def test_install_voice_installs_sounddevice_not_pyaudio():
    calls = []
    rep = install_voice(runner=lambda args: calls.append(args) or (0, "ok"))
    assert len(calls) == 1  # one pip call: SpeechRecognition + pyttsx3 + sounddevice
    assert "sounddevice" in calls[0] and "pyaudio" not in calls[0]
    assert rep.steps[0].ok and isinstance(rep, SetupReport)


def test_install_voice_reports_pip_failure_without_raising():
    rep = install_voice(runner=lambda args: (1, "ReadTimeoutError: connection timed out"))
    assert not rep.steps[0].ok and "네트워크" in rep.steps[0].detail
    assert "❌" in rep.render()


def test_check_voice_never_raises_and_reports_every_step():
    rep = check_voice()
    names = [s.name for s in rep.steps]
    assert any("SpeechRecognition" in n for n in names)
    assert any("마이크 입력 라이브러리" in n for n in names)  # sounddevice (preferred) or PyAudio
    assert all(isinstance(s, StepResult) for s in rep.steps)
    assert rep.render()
