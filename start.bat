@echo off
REM One-click launcher for TF2 Spray EasyImport.
REM Creates the virtual environment and installs dependencies on first run,
REM then starts the local web app.
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo Creating virtual environment...
    py -3 -m venv .venv 2>nul || python -m venv .venv
    if not exist ".venv\Scripts\python.exe" (
        echo.
        echo ERROR: Could not create a Python virtual environment.
        echo Make sure Python 3.12+ is installed and on PATH.
        pause
        exit /b 1
    )
    echo Installing dependencies - first run only...
    ".venv\Scripts\python.exe" -m pip install --upgrade pip
    ".venv\Scripts\python.exe" -m pip install -r requirements.txt
)

".venv\Scripts\python.exe" run.py
REM Keep the window open so startup errors stay readable.
if errorlevel 1 pause
endlocal
