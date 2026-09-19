#!/usr/bin/env bash
# ARIUS 설치 (macOS / Linux). 실행: bash install.sh
set -u
cd "$(dirname "$0")"
export PYTHONUTF8=1

echo "=========================================="
echo "  ARIUS 설치 (macOS / Linux)"
echo "=========================================="
echo

PY=""
for c in python3 python; do
  if command -v "$c" >/dev/null 2>&1; then PY="$c"; break; fi
done
if [ -z "$PY" ]; then
  echo "[오류] Python이 없습니다. https://www.python.org/downloads/ 에서 3.10 이상을 설치하십시오."
  echo "       (macOS: brew install python / Ubuntu: sudo apt install python3 python3-venv)"
  exit 1
fi
if ! "$PY" -c 'import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)'; then
  echo "[오류] Python 3.10 이상이 필요합니다. 현재: $("$PY" --version 2>&1)"
  exit 1
fi
echo "Python 확인: $("$PY" --version 2>&1)"
echo

if [ ! -x ".venv/bin/python" ]; then
  echo "가상환경(.venv)을 만드는 중..."
  "$PY" -m venv .venv 2>/dev/null || echo "[경고] 가상환경을 만들지 못했습니다 (Ubuntu: sudo apt install python3-venv). 시스템 Python을 사용합니다."
fi
[ -x ".venv/bin/python" ] && PY=".venv/bin/python"
echo

read -r -p "음성 기능(마이크 인식 + 음성 출력)을 설치할까요? [Y/n]: " EXTRAS || EXTRAS=""
if [[ ! "${EXTRAS:-}" =~ ^[Nn]$ ]]; then
  "$PY" -m pip install --upgrade pip >/dev/null 2>&1 || true
  "$PY" main.py setup voice || true
fi
read -r -p "Claude 클라우드 연결용 패키지(anthropic)도 설치할까요? [y/N]: " CLOUD || CLOUD=""
if [[ "${CLOUD:-}" =~ ^[Yy]$ ]]; then
  "$PY" -m pip install anthropic || echo "[경고] anthropic 설치 실패 - 나중에 다시 시도하십시오."
fi
echo

if [ -f "config.json" ]; then
  echo "config.json 이 이미 있어 초기 설정을 건너뜁니다. (다시 하려면 config.json 을 지우고 재실행)"
else
  "$PY" main.py init
fi
chmod +x run.sh setup-voice.sh setup-autostart.sh 2>/dev/null || true
read -r -p "컴퓨터를 켤 때 ARIUS를 자동으로 시작할까요? [Y/n]: " AUTO || AUTO=""
if [[ ! "${AUTO:-}" =~ ^[Nn]$ ]]; then
  "$PY" main.py autostart enable || true
fi
echo
echo "=========================================="
echo "  설치 완료!  앞으로는  ./run.sh  로 실행하십시오."
echo "=========================================="
