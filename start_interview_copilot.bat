@echo off
setlocal
cd /d "%~dp0"

set "PYTHONW=%~dp0venv\Scripts\pythonw.exe"
if not exist "%PYTHONW%" (
    echo Could not find the project virtual environment:
    echo %PYTHONW%
    echo Run run_setup.bat first.
    pause
    exit /b 1
)

rem Launch the GUI without attaching a console window.
start "" "%PYTHONW%" "%~dp0run_app.py"
exit /b 0
