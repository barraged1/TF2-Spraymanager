@echo off
setlocal
cd /d "%~dp0backend"
if not exist "..\.venv\Scripts\python.exe" (
    echo Run start.bat once to set up the Python environment first.
    pause
    exit /b 1
)
"..\.venv\Scripts\python.exe" -m app.services.spray_randomizer %*
pause
endlocal
