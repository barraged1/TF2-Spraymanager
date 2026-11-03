@echo off
setlocal
cd /d "%~dp0backend"
if not exist "..\.venv\Scripts\python.exe" (
    echo Python environment not found.
    pause
    exit /b 1
)
"..\.venv\Scripts\python.exe" -m app.services.spray_randomizer --uninstall %*
pause
endlocal
