@echo off
title AI Shopping Assistant Launcher
cd /d "%~dp0"

REM Check if virtual environment python exists
if exist ".venv\Scripts\python.exe" (
    echo [Launcher] Using virtual environment Python...
    ".venv\Scripts\python.exe" run.py
    goto end
)

REM Check if system python command exists
where python >nul 2>nul
if %errorlevel% equ 0 (
    echo [Launcher] Using system python...
    python run.py
    goto end
)

REM Check if py command exists
where py >nul 2>nul
if %errorlevel% equ 0 (
    echo [Launcher] Using py launcher...
    py run.py
    goto end
)

echo [Error] Python was not found in your system PATH.
echo Please make sure Python 3.10+ is installed and check the box "Add Python to PATH" during installation.

:end
pause
