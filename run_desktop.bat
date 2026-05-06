@echo off
cd /d "%~dp0"

if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" "Desktop\desktop_app.py"
    goto :end
)

echo Python environment not found.
echo Run setup.bat first, then try run_desktop.bat again.
pause

:end
