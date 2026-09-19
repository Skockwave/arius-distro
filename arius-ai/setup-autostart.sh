#!/usr/bin/env bash
# 로그인 시 ARIUS 자동 시작 등록 (macOS LaunchAgent / Linux autostart). 실행: bash setup-autostart.sh
cd "$(dirname "$0")"
export PYTHONUTF8=1
if [ -x ".venv/bin/python" ]; then PY=".venv/bin/python"; else PY="$(command -v python3 || command -v python)"; fi
exec "$PY" main.py autostart enable "$@"
