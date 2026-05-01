@echo off
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo Virtual environment not found. Run setup.bat first.
    pause
    exit /b 1
)

".venv\Scripts\python.exe" -m pip install --upgrade pip
".venv\Scripts\python.exe" -m pip install -r requirements-facenet.txt --no-cache-dir

echo.
echo FaceNet backend install complete.
echo Start the system again using START_SYSTEM.bat.
pause
