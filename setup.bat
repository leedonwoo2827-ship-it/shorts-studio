@echo off
setlocal
cd /d "%~dp0"

echo [1/4] Creating venv...
if not exist venv\Scripts\python.exe (
  python -m venv venv 2>nul || py -3 -m venv venv
)
if not exist venv\Scripts\python.exe (
  echo [ERROR] Could not create venv. Install Python 3.10+ and make sure 'python' is on PATH.
  pause
  exit /b 1
)

echo [2/4] Installing core dependencies...
venv\Scripts\python -m pip install --upgrade pip
venv\Scripts\python -m pip install -r requirements.txt
if errorlevel 1 (
  echo [ERROR] core pip install failed. See messages above.
  pause
  exit /b 1
)

echo [3/4] Installing optional helpers (skipped if they fail)...
:: edge-tts = 영상공방 없이 새 목소리 TTS / pywinpty = agy 내장 호출용. 없어도 앱은 동작.
venv\Scripts\python -m pip install edge-tts pywinpty 2>nul && (echo   optional: OK) || (echo   optional: 일부 건너뜀 - 무시 가능)

echo [4/4] Preparing .env...
if not exist .env copy .env.example .env >nul

echo.
echo === 외부 도구 확인 (PATH) ===
where ffmpeg >nul 2>nul && (echo   ffmpeg : OK) || (echo   ffmpeg : [필수] 없음 -- winget install Gyan.FFmpeg)
where codex  >nul 2>nul && (echo   codex  : OK 로그인 필요시 codex login) || (echo   codex  : 없음 - AI는 codex/agy 또는 영상공방 백엔드 필요)
where agy    >nul 2>nul && (echo   agy    : OK) || (echo   agy    : 없음 - 선택)
echo.
echo 완료! run.bat 으로 실행하세요.
pause
