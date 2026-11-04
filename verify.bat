@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    echo Rita is not installed yet. Run run_rita.bat first or use setup.bat.
    pause
    exit /b 1
)
".venv\Scripts\python.exe" verify.py
if errorlevel 1 pause
