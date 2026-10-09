@echo off
setlocal EnableExtensions
title YouTube AI Factory - THU NGHIEM (DB tam, khong dung DB that)

rem Same app as CHAY_YOUTUBE_AI_FACTORY.bat, but every place it writes is a test
rem folder: database, project files, browser profiles and connections. The real
rem database (_HE_THONG\data\youtube_monitor.db) is never opened, so no migration
rem runs on it and no queued task of it is picked up by the workers.
rem Variables set here win over _HE_THONG\config\.env (the app only fills in
rem what is not set already).

cd /d "%~dp0_HE_THONG\app"

set "TEST_ROOT=%LOCALAPPDATA%\YouTubeAIFactory_THU_NGHIEM"
set "YOUTUBE_DATA_DIR=%TEST_ROOT%\data"
set "YOUTUBE_DB_PATH=%TEST_ROOT%\data\youtube_monitor_thu_nghiem.db"
set "PRODUCTION_ARTIFACT_DIR=%TEST_ROOT%\projects"
set "WEB_VIDEO_STATE_DIR=%TEST_ROOT%\web_video_sidecar"
set "YOUTUBE_PROFILES_DIR=%TEST_ROOT%\profiles"
set "YOUTUBE_CONNECTIONS_STORE=%TEST_ROOT%\profiles\connections.json"
set "PYTHONIOENCODING=utf-8"
set "PYTHONUTF8=1"
set "YOUTUBE_AUTO_CLOSE_ON_BROWSER_EXIT=0"

echo.
echo ==========================================
echo   YOUTUBE AI FACTORY - CHE DO THU NGHIEM
echo ==========================================
echo DB thu nghiem : %YOUTUBE_DB_PATH%
echo File du an   : %PRODUCTION_ARTIFACT_DIR%
echo DB that KHONG duoc mo.
echo.
echo Luu y: cac nut goi AI (viet kich ban, lap ke hoach dung...) van dung
echo API key / Claude Code / Codex CLI dang co tren may nay neu ban bam.
echo Du lieu demo duoc tao bang model gia, khong goi AI.
echo.

netstat -ano | findstr /R /C:":8787 .*LISTENING" >nul 2>&1
if not errorlevel 1 (
    echo Cong 8787 dang duoc su dung - co the app that dang chay.
    echo Hay dong app do truoc roi chay lai file nay.
    echo.
    pause
    exit /b 1
)

set "PYTHON_EXE=C:\Program Files\Python313\python.exe"
if exist "%PYTHON_EXE%" (
    set PYCMD="%PYTHON_EXE%"
) else (
    where py >nul 2>&1
    if errorlevel 1 goto python_missing
    set PYCMD=py -3.13
)

if not exist "%YOUTUBE_DATA_DIR%" mkdir "%YOUTUBE_DATA_DIR%"
if not exist "%PRODUCTION_ARTIFACT_DIR%" mkdir "%PRODUCTION_ARTIFACT_DIR%"

echo Dang tao du lieu demo Buoc 5 (chi lan dau, DB thu nghiem)...
%PYCMD% -B "%~dp0_HE_THONG\scripts\seed_demo_buoc5.py"
if errorlevel 1 (
    echo Khong tao duoc du lieu demo. Xem loi o tren. App van se chay voi DB thu nghiem.
    echo.
)

echo.
echo Mo trinh duyet: http://127.0.0.1:8787
echo Kiem tra DB  : http://127.0.0.1:8787/api/health  (truong "database" phai la DB thu nghiem o tren)
echo Nhan Ctrl+C de dung server.
echo.
start "" "http://127.0.0.1:8787"
%PYCMD% -B -m uvicorn youtube_monitor.main:app --host 127.0.0.1 --port 8787
echo.
echo Server thu nghiem da dung.
exit /b 0

:python_missing
echo Khong tim thay Python 3.13.
pause
exit /b 1
