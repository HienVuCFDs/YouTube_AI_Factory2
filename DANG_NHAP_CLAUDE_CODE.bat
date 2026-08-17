@echo off
setlocal EnableExtensions
title Dang nhap Claude Code CLI

set "CLAUDE_CONFIG_DIR=%LOCALAPPDATA%\YouTubeAIFactory\claude_code_cli_profile"
if not exist "%CLAUDE_CONFIG_DIR%" mkdir "%CLAUDE_CONFIG_DIR%"

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
echo Day la mot ho so dang nhap rieng cho YouTube AI Factory,
echo tach biet voi Claude Code ban dang dung de sua code (neu co).
echo Hoan tat dang nhap trong cua so/trinh duyet duoc mo ra.
echo Sau do quay lai YouTube AI Factory va bam "Kiem tra lai".
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
