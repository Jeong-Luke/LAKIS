@echo off
setlocal
cd /d "%~dp0"
set "PORTABLE_PY=%~dp0..\..\..\python_embeded\python.exe"

if exist "%PORTABLE_PY%" (
  "%PORTABLE_PY%" -m pip install -r requirements.txt
  if errorlevel 1 (
    echo.
    echo [LAKIS] Installation failed.
    pause
    exit /b 1
  )
  echo.
  echo [LAKIS] Requirements installed. Restart ComfyUI.
  pause
  exit /b 0
)

python -m pip install -r requirements.txt
pause
