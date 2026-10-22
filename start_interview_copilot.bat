@echo off
setlocal
cd /d "%~dp0"

set "PYTHONW=%~dp0venv\Scripts\pythonw.exe"
if not exist "%PYTHONW%" (
    echo Could not find the project virtual environment:
    echo %PYTHONW%
    echo Create the environment and install dependencies first:
    echo   python -m venv venv
    echo   .\venv\Scripts\python.exe -m pip install -r requirements.txt
    echo Then create .env from .env.example and add your API key.
    pause
    exit /b 1
)

rem Launch the GUI without attaching a console window.
start "" "%PYTHONW%" "%~dp0app\run_app.py"
exit /b 0
