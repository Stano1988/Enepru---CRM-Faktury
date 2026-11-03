@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  py -3 -m venv .venv
  if errorlevel 1 goto fail
)
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto fail
".venv\Scripts\python.exe" manage.py migrate
if errorlevel 1 goto fail
".venv\Scripts\python.exe" manage.py shell -c "from django.contrib.auth import get_user_model; import sys; sys.exit(0 if get_user_model().objects.filter(is_superuser=True).exists() else 1)"
if errorlevel 1 (
  echo Vytvorte si vlastni spravcovsky ucet:
  ".venv\Scripts\python.exe" manage.py createsuperuser
  if errorlevel 1 goto fail
)
set CRM_DEBUG=1
set CRM_ALLOWED_HOSTS=localhost,127.0.0.1
start "" "http://127.0.0.1:8000"
echo CRM bezi pouze na tomto pocitaci. Ukonceni: Ctrl+C.
".venv\Scripts\python.exe" manage.py runserver 127.0.0.1:8000 --noreload
goto end
:fail
echo Spusteni se nezdarilo. Zkontrolujte chybu vyse a instalaci Pythonu 3.12 nebo novejsiho.
pause
:end
endlocal
