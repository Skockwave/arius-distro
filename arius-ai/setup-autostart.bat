@echo off
chcp 65001 >nul
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
cd /d "%~dp0"
title ARIUS 자동 시작 설정
if exist ".venv\Scripts\python.exe" (set "PY=.venv\Scripts\python.exe" & goto :run)
where py >nul 2>&1 && (set "PY=py -3" & goto :run)
set "PY=python"
:run
echo 컴퓨터를 켜면(로그인하면) ARIUS가 자동으로 시작되도록 등록합니다.
echo   - 서버 감시(하트비트) + 디스코드 대화 + 이름 부르면 대답(음성)
echo.
set "HIDE=n"
set /p HIDE=창 없이 백그라운드로 실행할까요? (n = 최소화된 창으로 보임) [y/N]:
if /i "%HIDE%"=="y" (
  %PY% main.py autostart enable --hidden
) else (
  %PY% main.py autostart enable
)
echo.
echo 해제하려면: 이 폴더에서  run.bat autostart disable
pause
