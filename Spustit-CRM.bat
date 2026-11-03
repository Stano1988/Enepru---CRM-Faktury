@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  py -3 -m venv .venv
  if errorlevel 1 goto fail
)
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto fail
".venv\Scripts\python.exe" run_crm.py
goto end
:fail
echo Spusteni se nezdarilo. Zkontrolujte chybu vyse a instalaci Pythonu 3.12 nebo novejsiho.
pause
:end
endlocal
