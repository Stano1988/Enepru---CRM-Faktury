@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Nejprve spustte Spustit-CRM.bat.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" configure_web.py
pause
endlocal
