@echo off
setlocal EnableExtensions
title YouTube AI Factory - kiem tra DB (chi doc)

rem Read-only: which database CHAY_YOUTUBE_AI_FACTORY.bat would open, whether
rem starting it would create tables, and which queued or running jobs its
rem workers would pick up. Nothing is written, not even SQLite -wal/-shm files.

cd /d "%~dp0_HE_THONG\app"
set "PYTHONIOENCODING=utf-8"
set "PYTHONUTF8=1"
set "PYTHON_EXE=C:\Program Files\Python313\python.exe"
if exist "%PYTHON_EXE%" (
    "%PYTHON_EXE%" -B "%~dp0_HE_THONG\scripts\kiem_tra_db.py"
) else (
    py -3.13 -B "%~dp0_HE_THONG\scripts\kiem_tra_db.py"
)
echo.
pause
