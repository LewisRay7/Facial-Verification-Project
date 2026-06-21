@echo off
setlocal
cd /d "%~dp0"

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0START_FACE_BACKEND.ps1"
if errorlevel 1 (
    echo ExamVerify could not start the desktop face engine.
    echo Review "%~dp0face-backend.err" for details.
    pause
    exit /b 1
)

start "ExamVerify Desktop" /D "%~dp0" "%~dp0examverify_app.exe"
