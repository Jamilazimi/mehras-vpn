@echo off
setlocal
cd /d "%~dp0"
title وی پی ان شخصی مهراس

where python >nul 2>&1
if errorlevel 1 (
    echo Python not found. Install Python 3.10+ from python.org and tick "Add to PATH".
    pause
    exit /b 1
)

if not exist ".deps_installed" (
    echo Installing dependencies...
    python -m pip install --disable-pip-version-check -r requirements.txt
    if errorlevel 1 (
        echo Failed to install dependencies.
        pause
        exit /b 1
    )
    echo ok > .deps_installed
)

REM Run the GUI without a console window
start "" pythonw main.py
exit /b 0
