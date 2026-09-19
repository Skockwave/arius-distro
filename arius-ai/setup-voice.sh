#!/usr/bin/env bash
# 음성 기능(마이크 인식 + 음성 출력) 설치·진단. 실행: bash setup-voice.sh
cd "$(dirname "$0")"
export PYTHONUTF8=1
if [ -x ".venv/bin/python" ]; then PY=".venv/bin/python"; else PY="$(command -v python3 || command -v python)"; fi
if [ "$(uname -s)" = "Darwin" ] && command -v brew >/dev/null 2>&1 && ! brew list portaudio >/dev/null 2>&1; then
  echo "PortAudio(마이크 라이브러리)를 Homebrew로 설치합니다..."; brew install portaudio || true
fi
exec "$PY" main.py setup voice
