@echo off
setlocal
cd /d "%~dp0"

set "PORT=7010"

if not exist venv\Scripts\python.exe (
  echo [ERROR] venv not found. Run setup.bat first.
  pause
  exit /b 1
)

echo ============================================================
echo   Shorts Studio - http://127.0.0.1:%PORT%/
echo   (Close this window to stop the server)
echo ============================================================
echo.

start "" /b cmd /c "timeout /t 3 >nul & start http://127.0.0.1:%PORT%/"

venv\Scripts\python -m uvicorn app:app --host 127.0.0.1 --port %PORT%

echo.
echo Server stopped (exit code %errorlevel%).
pause
