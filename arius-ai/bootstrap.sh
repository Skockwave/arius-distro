#!/usr/bin/env bash
# ARIUS one-line installer for macOS / Linux.
#
#   curl -fsSL https://raw.githubusercontent.com/Skockwave/arius-distro/main/arius-ai/bootstrap.sh | bash
#
# 하는 일: Python 확인 -> 코드 다운로드 -> ~/ARIUS 에 복사 -> install.sh 실행.
# 다시 실행해도 안전합니다: config.json 과 .venv 는 보존됩니다.
# 환경변수: ARIUS_DIR (설치 폴더), ARIUS_BRANCH (브랜치 강제), ARIUS_ARCHIVE_URL (tar.gz 주소 강제)
set -u
export PYTHONUTF8=1

REPO="Skockwave/arius-distro"
DEST="${ARIUS_DIR:-$HOME/ARIUS}"
BRANCHES=()
[ -n "${ARIUS_BRANCH:-}" ] && BRANCHES+=("$ARIUS_BRANCH")
BRANCHES+=("main" "claude/high-performance-ai-system-ibqiwl")

echo
echo "=========================================="
echo "  ARIUS 자동 설치 ($(uname -s))"
echo "=========================================="
echo

# --- 1) Python ---------------------------------------------------------------
have_python() {
  for c in python3 python; do
    if command -v "$c" >/dev/null 2>&1 && "$c" -c 'import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)' 2>/dev/null; then
      return 0
    fi
  done
  return 1
}
if have_python; then
  echo "[1/4] Python 3.10+ 확인됨."
else
  echo "[1/4] Python 3.10+ 가 없습니다."
  if [ "$(uname -s)" = "Darwin" ] && command -v brew >/dev/null 2>&1; then
    echo "      Homebrew 로 Python 을 설치합니다..."
    brew install python || true
  fi
  if ! have_python; then
    echo "      설치 방법:  macOS: brew install python   |  Ubuntu/Debian: sudo apt install python3 python3-venv"
    echo "      또는 https://www.python.org/downloads/ . 설치 후 이 명령을 다시 실행하십시오."
    exit 1
  fi
fi

# --- 2) Download -------------------------------------------------------------
TMP="$(mktemp -d 2>/dev/null || mktemp -d -t arius)"
trap 'rm -rf "$TMP"' EXIT
SRC_AI=""
URLS=()
[ -n "${ARIUS_ARCHIVE_URL:-}" ] && URLS+=("$ARIUS_ARCHIVE_URL")
for b in "${BRANCHES[@]}"; do URLS+=("https://github.com/$REPO/archive/refs/heads/$b.tar.gz"); done

for url in "${URLS[@]}"; do
  echo "[2/4] 다운로드: $url"
  rm -rf "$TMP/x"; mkdir -p "$TMP/x"
  if curl -fsSL "$url" | tar -xz -C "$TMP/x" 2>/dev/null; then
    cand="$(find "$TMP/x" -type f -path '*/arius-ai/main.py' | head -n1)"
    if [ -n "$cand" ]; then SRC_AI="$(dirname "$cand")"; break; fi
    echo "      이 브랜치에는 arius-ai 가 없습니다. 다음 후보를 시도합니다."
  else
    echo "      실패. 다음 후보를 시도합니다."
  fi
done
if [ -z "$SRC_AI" ]; then echo "코드를 내려받지 못했습니다. 인터넷 연결을 확인하십시오."; exit 1; fi

# --- 3) Copy (preserve config.json / .venv on re-run) --------------------------
echo "[3/4] 설치 폴더: $DEST"
mkdir -p "$DEST"
if command -v rsync >/dev/null 2>&1; then
  rsync -a --exclude config.json --exclude .venv --exclude __pycache__ --exclude .pytest_cache "$SRC_AI/" "$DEST/"
else
  ( cd "$SRC_AI" && tar --exclude=config.json --exclude=.venv --exclude=__pycache__ -cf - . ) | ( cd "$DEST" && tar -xf - )
fi
chmod +x "$DEST/install.sh" "$DEST/run.sh" 2>/dev/null || true

# --- 4) Install ----------------------------------------------------------------
echo "[4/4] 설치 스크립트를 실행합니다 (질문에 답해 주십시오)..."
cd "$DEST"
# stdin may be the pipe from curl; reattach the terminal so prompts work
if [ -t 1 ] && [ -r /dev/tty ]; then bash install.sh < /dev/tty; else bash install.sh; fi
echo
echo "설치 폴더: $DEST"
echo "실행:      $DEST/run.sh"
