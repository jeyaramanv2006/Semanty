@echo off
setlocal enabledelayedexpansion
title FindIT - Unified Runner
echo =====================================================================
echo                     FindIT - Universal Launcher
echo =====================================================================

set "PROJECT_ROOT=%~dp0"

:: Check if backend virtualenv or frontend node_modules is missing
set "NEED_SETUP=0"
if not exist "%PROJECT_ROOT%backend\.venv" set "NEED_SETUP=1"
if not exist "%PROJECT_ROOT%frontend\node_modules" set "NEED_SETUP=1"

if "%NEED_SETUP%"=="1" (
    echo.
    echo [FIRST RUN DETECTED] Virtual environment or packages missing.
    echo Running automated setup first...
    echo.
    call "%PROJECT_ROOT%scripts\setup.bat"
    if %ERRORLEVEL% neq 0 (
        echo [ERROR] Setup encountered an error.
        pause
        exit /b 1
    )
    echo.
    echo Setup completed! Proceeding to launch FindIT...
    echo.
)

:: Launch the primary Textual client. It owns the backend lifecycle when needed.
echo Starting FindIT Textual client ...
start "FindIT TUI" cmd /k "cd /d "%PROJECT_ROOT%" && call backend\.venv\Scripts\activate.bat && python -m tui"

echo.
echo =====================================================================
echo   FindIT is running!
echo   - Primary client: Textual TUI
echo   - Browser client: run scripts\start-frontend.bat separately
echo =====================================================================
echo.
exit
