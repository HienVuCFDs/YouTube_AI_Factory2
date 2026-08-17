@echo off
setlocal EnableExtensions
title Dang nhap Codex CLI

set "CODEX_HOME=%LOCALAPPDATA%\YouTubeAIFactory\codex_cli_profile"
if not exist "%CODEX_HOME%" mkdir "%CODEX_HOME%"

rem Extension version changes with every VS Code ChatGPT extension update, so
rem search for whatever version is currently installed instead of a pinned
rem path (a hardcoded version here previously went stale and silently broke
rem this launcher).
for /f "delims=" %%D in ('dir /b /ad /o-n "%USERPROFILE%\.vscode\extensions\openai.chatgpt-*" 2^>nul') do (
    if not defined CODEX_EXE if exist "%USERPROFILE%\.vscode\extensions\%%D\bin\windows-x86_64\codex.exe" set "CODEX_EXE=%USERPROFILE%\.vscode\extensions\%%D\bin\windows-x86_64\codex.exe"
)
if defined CODEX_EXE goto login

where codex >nul 2>&1
if errorlevel 1 goto missing
set "CODEX_EXE=codex"

:login
echo.
echo ==========================================
echo          DANG NHAP CODEX CLI
echo ==========================================
echo.
echo Hoan tat dang nhap trong cua so/trinh duyet duoc mo ra.
echo Sau do quay lai YouTube AI Factory va bam "Kiem tra lai".
echo.
"%CODEX_EXE%" login
echo.
pause
exit /b %ERRORLEVEL%

:missing
echo Khong tim thay Codex CLI tren may.
echo Hay cai/ca cap nhat extension ChatGPT trong VS Code roi thu lai.
echo.
pause
exit /b 1
