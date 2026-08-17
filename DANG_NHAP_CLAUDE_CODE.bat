@echo off
setlocal EnableExtensions
title Dang nhap Claude Code CLI

rem Unlike Codex, Claude Code CLI does not persist login credentials under a
rem redirected CLAUDE_CONFIG_DIR (verified: only a bare .claude.json shows up
rem there, never .credentials.json). So this uses the SAME account/profile as
rem your normal Claude Code CLI usage on this machine, not an isolated one.
rem If you are already logged in for everyday Claude Code use, YT Factory is
rem already logged in too - you likely do not need to run this at all.

rem Version changes with every VS Code Claude Code extension update, so
rem search for whatever version is currently installed instead of pinning one.
for /f "delims=" %%D in ('dir /b /ad /o-n "%USERPROFILE%\.vscode\extensions\anthropic.claude-code-*" 2^>nul') do (
    if not defined CLAUDE_EXE if exist "%USERPROFILE%\.vscode\extensions\%%D\resources\native-binary\claude.exe" set "CLAUDE_EXE=%USERPROFILE%\.vscode\extensions\%%D\resources\native-binary\claude.exe"
)
if defined CLAUDE_EXE goto login

where claude >nul 2>&1
if errorlevel 1 goto missing
set "CLAUDE_EXE=claude"

:login
echo.
echo ==========================================
echo       DANG NHAP CLAUDE CODE CLI
echo ==========================================
echo.
echo Day la CUNG mot tai khoan/ho so voi Claude Code ban dung hang ngay
echo (khong tach rieng duoc nhu Codex). Neu da dang nhap Claude Code roi
echo thi khong can chay file nay.
echo.
"%CLAUDE_EXE%" auth status
echo.
echo Neu o tren hien loggedIn: false, dang nhap ngay ben duoi:
echo.
"%CLAUDE_EXE%" auth login
echo.
pause
exit /b %ERRORLEVEL%

:missing
echo Khong tim thay Claude Code CLI tren may.
echo Hay cai/cap nhat extension Claude Code trong VS Code roi thu lai.
echo.
pause
exit /b 1
