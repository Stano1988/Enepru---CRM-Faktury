@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Nejprve spustte Spustit-CRM.bat a vytvorte spravcovsky ucet.
  pause
  exit /b 1
)
set /p CRM_LAN_IP=Zadejte IPv4 adresu vaseho PC z prikazu ipconfig (napr. 192.168.1.25): 
if not defined CRM_LAN_IP exit /b 1
set CRM_DEBUG=1
set "CRM_ALLOWED_HOSTS=localhost,127.0.0.1,%CRM_LAN_IP%"
echo Telefon musi byt na stejne duveryhodne Wi-Fi jako PC.
echo Na telefonu otevrete HTTP adresu tohoto PC s portem 8000.
echo Pouze testovaci data: toto lokalni spojeni neni sifrovane.
echo Ve Windows Firewall povolte pouze soukromou sit. Nenastavujte presmerovani portu na routeru.
echo Pro pristup odkudkoliv bude potreba soukrome nasazeni s HTTPS.
".venv\Scripts\python.exe" manage.py runserver 0.0.0.0:8000 --noreload
endlocal
