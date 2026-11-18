@echo off
rem One-click launcher for ww-echo.
rem
rem Env lookup order: repo .venv -> python on PATH.  (No machine-specific paths:
rem the old %TEMP%\ww-echo-venv313 fallback was a session artifact, not a requirement.)
rem
rem Admin is required because the game runs at High integrity; Medium cannot PostMessage (UIPI).
setlocal
cd /d "%~dp0"

set "PY=%~dp0.venv\Scripts\python.exe"
if not exist "%PY%" (
    where python >nul 2>nul
    if errorlevel 1 (
        echo [x] No Python found. Install Python 3.11+ and run:
        echo     python -m pip install -r requirements.txt
        pause
        exit /b 1
    )
    set "PY=python"
)

rem Fail fast with a fix hint instead of a stack trace deep inside Qt/OCR init.
"%PY%" -c "import cv2, PySide6" >nul 2>nul
if errorlevel 1 (
    echo [x] Dependencies missing in: %PY%
    echo     "%PY%" -m pip install -r requirements.txt
    pause
    exit /b 1
)

net session >nul 2>nul
if errorlevel 1 (
    echo [i] Requesting administrator rights...
    powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Process -FilePath '%~f0' -WorkingDirectory '%~dp0' -Verb RunAs"
    exit /b
)

echo [i] interpreter: %PY%
"%PY%" mainui.py
if errorlevel 1 pause
