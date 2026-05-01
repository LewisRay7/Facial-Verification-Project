@echo off
cd /d "%~dp0"
if exist .venv\Scripts\python.exe (
    .venv\Scripts\python.exe -m streamlit run App\app.py
) else (
    echo Virtual environment not found. Run setup.bat first.
    pause
)
