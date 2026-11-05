@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Nejprve spustte Spustit-CRM.bat a dokoncete instalaci.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto end
".venv\Scripts\python.exe" configure_mail.py
:end
pause
endlocal
