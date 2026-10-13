@echo off
title FindIT - Textual Client
set "PROJECT_ROOT=%~dp0.."
cd /d "%PROJECT_ROOT%"
call backend\.venv\Scripts\activate.bat
python -m tui
pause
