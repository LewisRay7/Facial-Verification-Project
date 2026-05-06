@echo off
cd /d "%~dp0"
title Exam Verification System

if exist "dist\ExamVerificationSystem\ExamVerificationSystem.exe" (
    start "" "dist\ExamVerificationSystem\ExamVerificationSystem.exe"
    exit /b 0
)

if exist ".venv\Scripts\python.exe" (
    start "" ".venv\Scripts\python.exe" "Desktop\desktop_app.py"
    exit /b 0
)

echo Exam Verification System could not start.
echo.
echo No packaged EXE was found and the Python virtual environment is missing.
echo Run setup.bat first, or build the EXE with build_desktop_exe.bat.
echo.
pause
