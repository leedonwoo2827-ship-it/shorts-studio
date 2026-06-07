@echo off
setlocal
cd /d "%~dp0"

echo [1/3] Creating venv...
if not exist venv\Scripts\python.exe (
  python -m venv venv 2>nul || py -3 -m venv venv
)
if not exist venv\Scripts\python.exe (
  echo [ERROR] Could not create venv. Install Python 3.10+ and make sure 'python' is on PATH.
  pause
  exit /b 1
)

echo [2/3] Installing dependencies...
venv\Scripts\python -m pip install --upgrade pip
venv\Scripts\python -m pip install -r requirements.txt
if errorlevel 1 (
  echo [ERROR] pip install failed. See messages above.
  pause
  exit /b 1
)

echo [3/3] Preparing .env...
if not exist .env copy .env.example .env >nul

echo.
where ffmpeg >nul 2>nul && (echo ffmpeg: OK) || (echo [WARN] ffmpeg not found on PATH -- install: winget install Gyan.FFmpeg)
echo.
echo Setup done. Now run: run.bat
pause
