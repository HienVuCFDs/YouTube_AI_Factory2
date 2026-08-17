@echo off
setlocal EnableExtensions
title YouTube AI Factory

cd /d "%~dp0_HE_THONG\app"

rem Force heavy Whisper/render stages onto GPU; no silent CPU fallback.
set "YOUTUBE_GPU_ONLY=1"
set "WHISPER_DEVICE=cuda"
set "WHISPER_COMPUTE_TYPE=float16"
set "CUDA_DEVICE=0"
set "PYTHONIOENCODING=utf-8"
set "PYTHONUTF8=1"
rem Keep the local server alive until the user explicitly closes the launcher.
set "YOUTUBE_AUTO_CLOSE_ON_BROWSER_EXIT=0"
set "YOUTUBE_BROWSER_IDLE_SECONDS=45"
set "YOUTUBE_BROWSER_CLOSE_GRACE_SECONDS=10"

echo.
echo ==========================================
echo       YOUTUBE AI FACTORY - KHOI DONG
echo ==========================================
echo.

netstat -ano | findstr /R /C:":8787 .*LISTENING" >nul 2>&1
if not errorlevel 1 (
    echo Cong 8787 dang duoc su dung.
    echo Hay mo trinh duyet tai: http://127.0.0.1:8787
    echo Neu app bi treo, hay dong cua so server cu roi chay lai file nay.
    echo.
    pause
    exit /b 1
)

set "PYTHON_EXE=C:\Program Files\Python313\python.exe"
if exist "%PYTHON_EXE%" goto start_server

where py >nul 2>&1
if errorlevel 1 goto python_missing

echo Dang khoi dong bang Python Launcher...
start "" "http://127.0.0.1:8787"
py -3.13 -B -m uvicorn youtube_monitor.main:app --host 127.0.0.1 --port 8787
goto server_stopped

:start_server
echo Dang khoi dong server local...
echo Trinh duyet se mo tai http://127.0.0.1:8787
echo Nhan Ctrl+C de dung server khi khong con dung.
echo.
start "" "http://127.0.0.1:8787"
"%PYTHON_EXE%" -B -m uvicorn youtube_monitor.main:app --host 127.0.0.1 --port 8787
goto server_stopped

:python_missing
echo Khong tim thay Python 3.13.
echo Can cai Python va cac thu vien cua project truoc khi chay app.
echo.
pause
exit /b 1

:server_stopped
echo.
echo Server da dung. Ket thuc launcher.
exit /b 0
