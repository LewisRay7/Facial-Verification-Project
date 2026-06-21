@echo off
setlocal
cd /d "%~dp0"

set "FACE_PORT=8765"
set "FACE_RUNNING="
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":%FACE_PORT%" ^| findstr "LISTENING"') do set "FACE_RUNNING=1"

if not defined FACE_RUNNING (
    if exist "%~dp0.venv\Scripts\python.exe" (
        start "ExamVerify Face Engine" /min /D "%~dp0face_backend" "%~dp0.venv\Scripts\python.exe" "App\backend_api.py" --host 127.0.0.1 --port %FACE_PORT%
    ) else (
        start "ExamVerify Face Engine" /min /D "%~dp0face_backend" python "App\backend_api.py" --host 127.0.0.1 --port %FACE_PORT%
    )
    timeout /t 5 /nobreak >nul
)

start "ExamVerify Desktop" /D "%~dp0" "%~dp0examverify_app.exe"
