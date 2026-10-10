@echo off
title E-Waste ChainGuard

echo Starting E-Waste ChainGuard...
echo.

:: Start backend in a new window
start "ChainGuard Backend" cmd /k "cd /d %~dp0backend && venv\Scripts\uvicorn.exe app.main:app --reload --port 8000"

:: Give the backend 2 seconds to bind before opening the browser hint
timeout /t 2 /nobreak > nul

:: Start frontend in a new window
start "ChainGuard Frontend" cmd /k "cd /d %~dp0frontend && npm run dev"

echo.
echo  Backend  ^>  http://localhost:8000
echo  API Docs ^>  http://localhost:8000/api/docs
echo  Frontend ^>  http://localhost:5173
echo.
echo Both servers are starting in separate windows.
pause
