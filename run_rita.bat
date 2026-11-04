@echo off
setlocal
cd /d "%~dp0"

set "NEED_SETUP=0"
if not exist ".venv\Scripts\python.exe" set "NEED_SETUP=1"
if "%NEED_SETUP%"=="0" (
    ".venv\Scripts\python.exe" -c "import customtkinter, groq; from google import genai" >nul 2>nul
    if errorlevel 1 set "NEED_SETUP=1"
)

if "%NEED_SETUP%"=="1" (
    echo Rita is preparing its Python environment for the first launch.
    call setup.bat
    if errorlevel 1 exit /b 1
)

call ".venv\Scripts\activate.bat"
python main.py
if errorlevel 1 (
    echo.
    echo [ERROR] Rita closed with an error. Run verify.bat to collect diagnostics.
    pause
)
