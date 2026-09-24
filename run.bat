@echo off
cd /d "%~dp0"
if not exist ".\venv\Scripts\python.exe" (
    echo Error: Virtual environment not found at .\venv
    echo Please create it: python -m venv venv
    echo And install dependencies: .\venv\Scripts\pip.exe install -r requirements.txt
    pause
    exit /b 1
)
.\venv\Scripts\python.exe run_app.py %*
