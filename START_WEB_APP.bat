@echo off
cd /d "%~dp0"
title EVS Web App

if exist ".venv\Scripts\python.exe" (
    echo Starting Streamlit web app...
    echo.
    echo Open http://localhost:8501 in your browser.
    ".venv\Scripts\python.exe" -m streamlit run "App\app.py" --server.port 8501
    exit /b 0
)

echo Streamlit web app could not start.
echo.
echo Python environment not found.
echo Run setup.bat first, then try START_WEB_APP.bat again.
echo.
pause
