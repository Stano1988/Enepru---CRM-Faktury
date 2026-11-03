# Spuštění na Windows a Androidu

## Windows zdarma

1. Nainstalujte Python 3.12 nebo novější z https://www.python.org/downloads/windows/ včetně launcheru `py`.
2. Na GitHubu zvolte **Code → Download ZIP**.
3. ZIP rozbalte do vlastní složky, například Dokumenty\LahodnyCRM.
4. Dvojklikem spusťte **Spustit-CRM.bat**. První instalace potřebuje internet.
5. Při prvním spuštění vytvořte vlastní účet správce. Heslo se v terminálu nezobrazuje.
6. Prohlížeč se otevře automaticky. Pokud stránka není hned připravená, obnovte ji.
7. Terminál nechte otevřený. Ukončení: Ctrl+C.

Každé další spuštění je opět dvojklikem. Používá se Waitress bez debug režimu; data zůstávají v rozbalené složce. Není vytvořené žádné výchozí heslo. Nejdříve používejte pouze testovací údaje.

## Android přes domácí Wi-Fi

1. Nejprve dokončete první spuštění na PC. Server zastavte pomocí Ctrl+C.
2. Telefon a PC připojte ke stejné důvěryhodné domácí síti.
3. Na PC otevřete Příkazový řádek a spusťte `ipconfig`. Najděte IPv4 adresu aktivního připojení.
4. Spusťte **Spustit-CRM-WiFi.bat** a zadejte tuto adresu.
5. Firewall případně povolte pouze pro soukromou síť.
6. Na telefonu otevřete v Chrome HTTP adresu PC s portem 8000, například `http://192.168.1.25:8000`.
7. Přihlaste se stejným účtem. PC musí být zapnutý a server spuštěný.

Tato domácí varianta není šifrované HTTPS spojení. Nepoužívat na veřejné Wi-Fi, neotvírat porty routeru a nevypínat firewall. Mobilní data a přístup mimo domov vyžadují samostatné HTTPS nasazení.

## Aktualizace a zálohy

V Nastavení lze stáhnout úplnou zálohu. Před aktualizací aplikaci zastavte, zazálohujte a zachovejte `db.sqlite3`, `media/` a `.local-secret`. Stažení nové verze do jiné složky samo nepřenese vaše data. Při nejistotě pokračujte se správcem, nepřepisujte původní složku.

## Rozsah ověření

Waitress, migrace, formuláře a obrazovky byly ověřeny na Linuxu v reálném Chromium včetně mobilního rozměru. Windows dávkové soubory a skutečný Android ještě nebyly na těchto zařízeních spuštěny. Případnou chybu z terminálu pošlete jako text bez hesel.
