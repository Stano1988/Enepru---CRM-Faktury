@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Nejprve spustte Spustit-CRM.bat a vytvorte spravcovsky ucet.
  pause
  exit /b 1
)
set /p "CRM_LAN_IP=Zadejte IPv4 adresu PC z prikazu ipconfig (napr. 192.168.1.25): "
if not defined CRM_LAN_IP exit /b 1
echo Pouze duveryhodna domaci Wi-Fi. Firewall povolte pouze pro soukromou sit.
echo Na routeru neotvirejte porty. PC musi zustat zapnuty.
".venv\Scripts\python.exe" run_crm.py --lan "%CRM_LAN_IP%"
if errorlevel 1 pause
endlocal
