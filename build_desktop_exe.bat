@echo off
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo Python environment not found.
    echo Run setup.bat first, then try again.
    pause
    exit /b 1
)

".venv\Scripts\python.exe" -m pip show pyinstaller >nul 2>nul
if errorlevel 1 (
    echo PyInstaller is not installed in the virtual environment.
    echo Run:
    echo .venv\Scripts\python.exe -m pip install pyinstaller
    pause
    exit /b 1
)

".venv\Scripts\python.exe" -m PyInstaller ^
    --noconfirm ^
    --clean ^
    --windowed ^
    --name "ExamVerificationSystem" ^
    --icon "Assets\exam_verification_logo.ico" ^
    --add-data "SRC;SRC" ^
    --add-data "Data;Data" ^
    --add-data "Assets;Assets" ^
    --add-data "Models;Models" ^
    "Desktop\desktop_app.py"

echo.
echo Build complete. Check dist\ExamVerificationSystem\ExamVerificationSystem.exe
pause
