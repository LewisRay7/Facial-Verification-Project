@echo off
cd /d "%~dp0"

if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" -m streamlit run "App\app.py"
    goto :end
)

if exist "%LOCALAPPDATA%\Programs\Python\Python311\python.exe" (
    "%LOCALAPPDATA%\Programs\Python\Python311\python.exe" -m streamlit run "App\app.py"
    goto :end
)

echo Python environment not found.
echo Run setup.bat first, then try START_SYSTEM.bat again.
pause

:end
