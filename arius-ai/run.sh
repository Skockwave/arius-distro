#!/usr/bin/env bash
# ARIUS 실행 (macOS / Linux). 실행: ./run.sh   (음성: ./run.sh run --voice)
cd "$(dirname "$0")"
export PYTHONUTF8=1
if [ -x ".venv/bin/python" ]; then
  PY=".venv/bin/python"
else
  PY="$(command -v python3 || command -v python)"
fi
exec "$PY" main.py "$@"
