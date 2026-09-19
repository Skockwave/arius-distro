@echo off
chcp 65001 >nul
setlocal
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
cd /d "%~dp0"

echo ==========================================
echo   ARIUS 설치 (Windows)
echo ==========================================
echo.

where py >nul 2>&1 && (set "PY=py -3" & goto :found)
where python >nul 2>&1 && (set "PY=python" & goto :found)
echo [오류] Python이 설치되어 있지 않습니다.
echo   1. https://www.python.org/downloads/ 에서 Python 3.10 이상을 받으십시오.
echo   2. 설치 화면 맨 아래 "Add python.exe to PATH" 를 꼭 체크하십시오.
echo   3. 설치 후 이 파일(install.bat)을 다시 실행하십시오.
pause
exit /b 1

:found
%PY% -c "import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)" >nul 2>&1
if errorlevel 1 (
  echo [오류] Python 3.10 이상이 필요합니다. 현재:
  %PY% --version
  pause
  exit /b 1
)
echo Python 확인:
%PY% --version
echo.

if not exist ".venv\Scripts\python.exe" (
  echo 가상환경(.venv)을 만드는 중...
  %PY% -m venv .venv
)
if exist ".venv\Scripts\python.exe" (
  set "PY=.venv\Scripts\python.exe"
) else (
  echo [경고] 가상환경을 만들지 못했습니다. 시스템 Python을 그대로 사용합니다.
)
echo.

set "EXTRAS=y"
set /p EXTRAS=음성 기능(마이크 인식 + 음성 출력)을 설치할까요? [Y/n]:
if /i not "%EXTRAS%"=="n" (
  %PY% -m pip install --upgrade pip >nul 2>&1
  %PY% main.py setup voice
)
set "CLOUD=n"
set /p CLOUD=Claude 클라우드 연결용 패키지(anthropic)도 설치할까요? [y/N]:
if /i "%CLOUD%"=="y" %PY% -m pip install anthropic
echo.

if exist "config.json" (
  echo config.json 이 이미 있어 초기 설정을 건너뜁니다. (다시 하려면 config.json 을 지우고 재실행)
) else (
  %PY% main.py init
)
echo.
echo ==========================================
echo   설치 완료!
echo   앞으로는 run.bat 을 더블클릭해 실행하십시오.
echo   바탕화면 바로가기: run.bat 우클릭 - 보내기 - 바탕 화면(바로 가기 만들기)
echo ==========================================
pause
endlocal
