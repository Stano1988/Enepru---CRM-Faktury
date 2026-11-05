# Provoz a bezpečná konfigurace

## Lokální data

- `db.sqlite3`: databáze včetně účtů.
- `media/`: neveřejné soubory. Nezpřístupňovat přímo webovým serverem.
- `.local-secret`: lokální tajný klíč. Zachovat a nesdílet.

Přesměrování úložišť: `CRM_DB_PATH`, `CRM_MEDIA_ROOT`. Pro produkci dodat `CRM_SECRET_KEY` přes správce tajných údajů. Nic z toho nepatří na GitHub. Ukázková data a hesla pro kontrolu nebyla vložena do projektu.

## E-mail

Pro Windows je k dispozici `Pripojit-postu.bat` a systémový Správce pověření. Podrobnosti jsou v [INTEGRATIONS.md](INTEGRATIONS.md). Soubor `.mail-settings.json` neobsahuje heslo a není součástí Git ani běžné datové zálohy. Na jiném PC je potřeba poštu znovu připojit. Proměnné prostředí mají před lokálním profilem přednost.


Bez připojení SMTP lze zprávy připravovat a kontrolovat; nikdy se neoznačí jako skutečně odeslané.

Konfigurace pomocí proměnných cílového prostředí:

- `CRM_EMAIL_ENABLED=1`
- `CRM_SMTP_HOST`: ověřený server poskytovatele.
- `CRM_SMTP_PORT`: obvykle 587 pro STARTTLS.
- `CRM_SMTP_TLS=1`, `CRM_SMTP_SSL=0` pro STARTTLS; pro přímé SSL použít opačné nastavení a odpovídající port.
- `CRM_SMTP_USER`: uživatelské jméno.
- `CRM_SMTP_PASSWORD`: pouze ze zabezpečeného úložiště, nikdy do chatu nebo Gitu.
- `CRM_FROM_EMAIL`: adresa oprávněného odesílatele.

Seznam účet musí povolovat daný způsob přihlášení; případné heslo aplikace vytvořit u poskytovatele. Konkrétní živé odeslání nebylo ověřeno. Poštovní server může vyžadovat síťové povolení v cílovém prostředí. Stav „odesláno“ znamená přijetí SMTP serverem, nikoliv důkaz doručení příjemci.

Při pádu během odesílání může zůstat zpráva ve stavu „Odesílá se“. Neopakovat ji automaticky; nejprve ověřit skutečné doručení. SMTP nemůže obecně zaručit přesně jedno doručení.

## Automatizace

`run_crm.py` každých pět minut kontroluje upozornění a upomínky. Na hostingu spouštět pravidelně:

```sh
.venv/bin/python manage.py run_automations
```

Pravidla upomínek jsou v administraci → Automatizace. Výchozí stav: příprava návrhů zapnutá, automatické odesílání vypnuté. První, druhý a třetí stupeň se řídí počtem dnů od splatnosti. Při úhradě se návrhy zruší, při sporu lze upomínky pozastavit.

Automatické potvrzení přijetí poptávky se po připojení SMTP zpracovává stejnou periodickou úlohou. Ostatní obchodní zprávy vyžadují kontrolu a ruční odeslání.

## Bankovní CSV

UTF-8, oddělovač středník:

```csv
id;date;amount;vs;note
unikatni-bankovni-id;2027-01-15;12000.00;2700101;Uhrada
```

Pouze kladné příjmy v CZK. Stejné ID nesmí mít odlišný obsah. Automaticky se přiřadí jen shodný VS a přesná zbývající částka; ostatní řádky se řeší ručně. Nejde o ověřený nativní formát MONETA ani přímé napojení banky.

## Záloha a obnova

Zálohu lze stáhnout v Nastavení. Obsahuje přihlašovací databázi a soukromé dokumenty, ukládat šifrovaně mimo zařízení. Alternativně:

```sh
.venv/bin/python manage.py backup_crm --output /bezpecna/cesta/zaloha.zip
.venv/bin/python manage.py restore_crm /bezpecna/cesta/zaloha.zip --destination /nova/slozka
```

Příkaz obnovy neumožní přepsat existující složku. Zkontroluje cesty, SHA-256 a integritu SQLite. Pro přepnutí zastavit server, uchovat současná data, nastavit `CRM_DB_PATH` a `CRM_MEDIA_ROOT` na obnovené složky. `.local-secret` nebo odpovídající `CRM_SECRET_KEY` zálohovat odděleně. Rotace klíče zneplatní existující relace a odkazy obnovy hesla.

Před velkou zálohou zastavit nahrávání souborů; pro velký produkční provoz použít spravovanou databázi a zálohovací nástroj. Samotná kopie na stejném disku nechrání před jeho ztrátou.

## Před veřejným nasazením

Aplikace zatím není veřejně nasazená. Použít HTTPS, explicitní `CRM_ALLOWED_HOSTS`, bezpečný klíč, `CRM_HTTPS=1`, ověřenou proxy konfiguraci, oddělené zálohy a monitoring. Vývojový server nezveřejňovat. Pro větší zátěž připravit PostgreSQL migraci a její testy; aktuální běhová konfigurace používá SQLite s IMMEDIATE transakcemi.

Zapnout MFA správci, ověřit role na reálném scénáři, otestovat obnovu a skutečné SMTP. Právně ověřit faktury, zásady zpracování osobních údajů a doby uchování. Případné vystavení údajů přes ARES potřebuje povolený HTTPS přístup na ares.gov.cz.

## Nezávislé agendy a archiv

Pracovní archiv je oddělený od financí. Po archivaci lze vystavovat faktury a zaznamenávat platby; nelze přepisovat uzamčené pracovní dokumenty. Export obsahuje původní manifest práce a samostatný `finance-current.json` s aktuálním stavem financí. Záznam předání ani uhrazená faktura nejsou předpokladem archivace. Minimální doba uchování v aplikaci je 5 let; delší právní lhůty je nutné ověřit podle dokumentu.
