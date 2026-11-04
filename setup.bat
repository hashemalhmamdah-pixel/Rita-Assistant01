@echo off
setlocal
cd /d "%~dp0"

echo ========================================
echo       Rita Assistant - Setup
echo ========================================
echo.

REM Rita currently targets regular (GIL-enabled) 64-bit CPython 3.15.x.
REM The Python Install Manager's current Python command selects its current default.
REM The explicit py -3.15 selector is preferred when it is available.

set "PYTHON="
where py >nul 2>nul
if not errorlevel 1 (
    py -3.15 -c "import sys,sysconfig; assert sys.implementation.name == 'cpython' and sys.version_info[:2] == (3,15) and sys.maxsize > 2**32 and not sysconfig.get_config_var('Py_GIL_DISABLED')" >nul 2>nul
    if not errorlevel 1 set "PYTHON=py -3.15"
)

if not defined PYTHON (
    python -c "import sys,sysconfig; assert sys.implementation.name == 'cpython' and sys.version_info[:2] == (3,15) and sys.maxsize > 2**32 and not sysconfig.get_config_var('Py_GIL_DISABLED')" >nul 2>nul
    if not errorlevel 1 set "PYTHON=python"
)

if not defined PYTHON (
    echo [ERROR] Rita requires regular 64-bit CPython 3.15.x.
    echo Your current Python command must report Python 3.15.x and 64-bit.
    echo The free-threaded build is not supported by the current Windows wheels.
    echo Install the current Python from the official Python Install Manager:
    echo https://www.python.org/downloads/windows/
    pause
    exit /b 1
)

set "SELECTED_VERSION="
for /f "delims=" %%V in ('%PYTHON% -c "import sys; print(sys.version_info.major,sys.version_info.minor,sys.version_info.micro,sep=chr(46))"') do set "SELECTED_VERSION=%%V"
if not defined SELECTED_VERSION goto :failed

echo Using %PYTHON%
echo Selected Python version: %SELECTED_VERSION%
%PYTHON% -c "import sys,struct; print('Runtime:',sys.implementation.name, '-', struct.calcsize('P')*8, 'bit')"
if errorlevel 1 goto :failed

REM Recreate the virtual environment if it was made with another Python patch release.
if exist ".venv\Scripts\python.exe" (
    set "VENV_VERSION="
    for /f "delims=" %%V in ('".venv\Scripts\python.exe" -c "import sys; print(sys.version_info.major,sys.version_info.minor,sys.version_info.micro,sep=chr(46))"') do set "VENV_VERSION=%%V"
    call :compare_versions
    if errorlevel 1 (
        echo Recreating the old virtual environment for Python %SELECTED_VERSION%...
        rmdir /s /q ".venv"
        if exist ".venv" goto :failed
    )
)

if not exist ".venv\Scripts\python.exe" (
    %PYTHON% -m venv .venv
    if errorlevel 1 goto :failed
)

call ".venv\Scripts\activate.bat"
python -c "import sys,sysconfig; assert sys.implementation.name == 'cpython' and sys.version_info[:2] == (3,15) and sys.maxsize > 2**32 and not sysconfig.get_config_var('Py_GIL_DISABLED')"
if errorlevel 1 goto :failed

python -m pip install --upgrade pip
if errorlevel 1 goto :failed

REM Remove conflicting packages from older attempts; pygame-ce still imports as pygame.
python -m pip uninstall -y pygame PyAudio >nul 2>nul

REM Require prebuilt Windows wheels for packages with native components.
python -m pip install --only-binary=:all: "pygame-ce==2.5.8" "sounddevice==0.5.6" "Pillow>=13.0,<14.0" "pywin32>=312"
if errorlevel 1 (
    echo.
    echo [ERROR] A required Python 3.15 Windows wheel could not be installed.
    echo Confirm regular 64-bit CPython 3.15.x and a working internet connection.
    goto :failed
)

python -m pip install -r requirements.txt
if errorlevel 1 goto :failed

python -c "import pygame, sounddevice, PIL, win32api, customtkinter, groq; from google import genai; from voice import AssistantVoice; AssistantVoice._install_removed_audio_module_shims(); import speech_recognition; print('UI, AI, native and voice package imports: OK')"
if errorlevel 1 goto :failed

if not exist ".env" copy ".env.example" ".env" >nul

echo.
echo [SUCCESS] Setup completed for Python %SELECTED_VERSION%.
echo Local AI provider credentials are already configured in .env.
echo Keep this folder private because .env contains API credentials.
echo Run Rita with run_rita.bat.
pause
exit /b 0

:compare_versions
if "%VENV_VERSION%"=="%SELECTED_VERSION%" exit /b 0
exit /b 1

:failed
echo.
echo [ERROR] Setup failed. The virtual environment was not confirmed ready.
echo Read the error above, fix it, then run setup.bat again.
pause
exit /b 1
