@echo off
chcp 65001 >nul
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
cd /d "%~dp0"
title ARIUS

if exist ".venv\Scripts\python.exe" (set "PY=.venv\Scripts\python.exe" & goto :run)
where py >nul 2>&1 && (set "PY=py -3" & goto :run)
set "PY=python"

:run
%PY% main.py %*
if errorlevel 1 (
  echo.
  echo [ARIUS 가 오류로 종료되었습니다. 위 메시지를 확인하십시오. Python이 없다면 install.bat 을 먼저 실행하십시오.]
  pause
)
