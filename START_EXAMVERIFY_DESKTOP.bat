@echo off
setlocal
cd /d "%~dp0"

set "CLOUD_PORT=8000"
set "FACE_PORT=8765"
if not exist ".matplotlib-cache" mkdir ".matplotlib-cache" >nul 2>nul
set "MPLCONFIGDIR=%~dp0.matplotlib-cache"
set "JWT_SECRET=local-test-secret-change-before-render"
set "SUPER_ADMIN_EMAIL=ngubaimutale7@gmail.com"
set "SUPER_ADMIN_PASSWORD=Admin@12345"

set "CLOUD_RUNNING="
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":%CLOUD_PORT%" ^| findstr "LISTENING"') do set "CLOUD_RUNNING=1"

if not defined CLOUD_RUNNING (
    if exist "%~dp0.venv\Scripts\python.exe" (
        start "ExamVerify Cloud API" /min "%~dp0.venv\Scripts\python.exe" -m uvicorn backend.main:app --host 0.0.0.0 --port %CLOUD_PORT%
    ) else (
        start "ExamVerify Cloud API" /min python -m uvicorn backend.main:app --host 0.0.0.0 --port %CLOUD_PORT%
    )
    ping -n 7 127.0.0.1 >nul
)

set "FACE_RUNNING="
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":%FACE_PORT%" ^| findstr "LISTENING"') do set "FACE_RUNNING=1"

if not defined FACE_RUNNING (
    if exist "%~dp0.venv\Scripts\python.exe" (
        start "ExamVerify Face Engine" /min "%~dp0.venv\Scripts\python.exe" "%~dp0App\backend_api.py" --host 0.0.0.0 --port %FACE_PORT%
    ) else (
        start "ExamVerify Face Engine" /min python "%~dp0App\backend_api.py" --host 0.0.0.0 --port %FACE_PORT%
    )
    ping -n 7 127.0.0.1 >nul
)

start "ExamVerify Desktop" "%~dp0examverify_app.exe"
