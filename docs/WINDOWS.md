# Vyzkoušení na Windows a Androidu

Toto je vývojová ukázka s testovacími údaji, nikoliv ostrý provoz.

## Windows

1. Nainstalujte Python 3.12 nebo novější z https://www.python.org/downloads/windows/ včetně Python launcheru `py`.
2. Na stránce repozitáře GitHub zvolte Code → Download ZIP.
3. ZIP rozbalte do běžné vlastní složky (např. Dokumenty\LahodnyCRM). Nespouštějte uvnitř ZIPu.
4. Dvojklikem spusťte `Spustit-CRM.bat`. První spuštění potřebuje internet pro instalaci závislostí.
5. Při prvním spuštění vytvořte vlastní účet. Při psaní hesla do terminálu se znaky nezobrazují.
6. Prohlížeč se otevře na http://127.0.0.1:8000. Pokud se otevře před dokončením startu, obnovte stránku.
7. Nejprve založte klienta a poté zakázku. Pro ukončení stiskněte v terminálu Ctrl+C.

Data zůstávají v `db.sqlite3` v rozbalené složce. `.local-secret` zachovejte. Složku nemažte ani nepřepisujte při aktualizaci bez zálohy. Databázi zálohujte při zastaveném serveru. Nesdílejte ji veřejně.

## Android přes domácí Wi-Fi

1. Nejprve dokončete první spuštění na PC. Zastavte běžný server pomocí Ctrl+C.
2. Telefon a PC připojte ke stejné důvěryhodné domácí síti; nepoužívejte veřejnou Wi-Fi.
3. Na PC otevřete Příkazový řádek a spusťte `ipconfig`. Najděte IPv4 adresu aktivního připojení, například `192.168.1.25`.
4. Spusťte `Spustit-CRM-WiFi.bat` a zadejte tuto adresu.
5. Pokud Windows požádá o povolení firewallu, povolte Python pouze pro soukromou síť.
6. V Chrome na Androidu otevřete například `http://192.168.1.25:8000` (nahraďte IP adresou vašeho PC).
7. Přihlaste se vlastním účtem. PC musí zůstat zapnutý a server spuštěný.

Mobilní přístup je pouze pro lokální testování s testovacími údaji: HTTP není šifrované a vývojový režim není produkční server. Na routeru neotvírejte porty a server nezveřejňujte. Některé sítě blokují komunikaci mezi zařízeními; nepřekonávejte to vypnutím firewallu.

Pro běžné použití z mobilních dat nebo mimo domov nasadíme CRM na soukromou HTTPS adresu, po dokončení provozního zabezpečení.

## Stav ověření

Django aplikace a HTTP odpovědi byly ověřeny na Linuxu. Windows spouštěcí skripty byly připraveny a zkontrolovány, ale na skutečném Windows ani Androidu zatím spuštěny nebyly. Případnou chybu z okna terminálu pošlete jako text bez hesel.
