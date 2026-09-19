@echo off
chcp 65001 >nul
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
cd /d "%~dp0"
title ARIUS 음성 설정
if exist ".venv\Scripts\python.exe" (set "PY=.venv\Scripts\python.exe" & goto :run)
where py >nul 2>&1 && (set "PY=py -3" & goto :run)
set "PY=python"
:run
%PY% main.py setup voice
echo.
pause
