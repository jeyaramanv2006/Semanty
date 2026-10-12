@echo off
title FindIT - Browser Client
set "PROJECT_ROOT=%~dp0.."
echo Starting FindIT backend and browser client...
start "FindIT Backend" cmd /k "cd /d "%PROJECT_ROOT%backend" && call .venv\Scripts\activate.bat && set FINDIT_RELOAD=1 && python run.py"
start "FindIT Frontend" cmd /k "cd /d "%PROJECT_ROOT%frontend" && npm run dev"
