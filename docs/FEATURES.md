# Stav požadavků

**Aktualizace 5. 11. 2026:** jednotlivé agendy mají fungovat samostatně; vazby jsou pomoc, nikoliv povinné pořadí. Cenová nabídka není podmínkou zakázky a zakázka není podmínkou faktury.

Tento soupis rozlišuje implementovanou funkci, provedenou kontrolu a nepřipojenou externí službu. Úplnou produkční připravenost netvrdíme.

| Oblast | Aktuální stav | Zbývající rozsah |
|---|---|---|
| Klienti a kontakty | Karta klienta, poznámky a požadavky, individuální splatnost, editace s historií, opakované použití, kontrola duplicit, kontaktní role a adresy | Řízené slučování duplicit, více firem u jednoho kontaktu |
| ARES | Načítací formulář, předvyplnění; test s mockovaným API | Skutečný přístup na ares.gov.cz je třeba ověřit v cílovém prostředí |
| Nemovitosti | Samostatná evidence, parcely, technické poznámky, vazba na zakázku | Podrobné strukturované odborné údaje a napojení na katastr |
| Webové poptávky | Formulář, přílohy, deduplikace, podepsané API pro více webů s vlastními klíči a zdroji | Změny skutečného enepru-web připravené a společně testované, zbývá nasadit na hosting; antispam pro větší provoz |
| Příjem e-mailu | EML, vytvoření poptávky tlačítkem, readonly IMAP, automatický převod vybrané složky, párování odpovědí a příloh | Ověření skutečné schránky Seznam; nastavení přes Windows průvodce nebo bezpečné proměnné |
| Nabídky | Verze, uložené PDF, cena, rozsah, podmínky, platnost, e-mailový návrh, potvrzení/odmítnutí klientem, připomínka | Živé doručování a konečná úprava vzhledu s majitelem; automatické odesílání nabídky se nezapíná bez kontroly |
| Zakázky | Převod i samostatné založení s novým klientem na místě, třídění a filtry, číslo, nemovitost, termíny, popis, historie a stav | Dílčí stavové workflow PENB/pasportu je nyní zastoupeno úkoly, nikoliv samostatnými stavovými kartami |
| Dokumenty | Samostatná knihovna i dokumenty u zakázek, pozdější přiřazení, složky, nahrávání, verze, metadata, koš a oprávnění | Přetažení, hromadné změny a antivirový skener; náhled PDF/obrázků a výběrový ZIP jsou implementované |
| Klientský přístup | Expirace, odvolání, nahrávání, požadavky, povolené finální výstupy | Klientský chat, volba termínu a potvrzení převzetí online |
| Termíny a práce | Vlastní soukromé zápisy bez zakázky, živé termíny dokončení, úkoly, zaměření, měsíční kalendář, hodiny a upozornění | Konflikty v kalendáři, automatické plánování kapacity, externí synchronizace |
| Vícepráce | Návrh, potvrzení odkazem, změna ceny a termínu, idempotence | Zamítnutí/revokace a přesné rozdělení do fakturačních položek |
| Faktury | Volný text a jedna cena bez povinných položek/katalogu, přenos ceny, individuální splatnost, automatické uložení nového klienta, PDF/QR, vystavení a příprava e-mailu | Opravné doklady, externě vystavené faktury a jejich import, více záloh na jedno vyúčtování, další měny a DPH |
| Excelová předloha | Hlavní prvky, údaje dodavatele, české popisky a QR | Přesné grafické doladění proti původnímu souboru s majitelem |
| Platby | Ruční, částečné, přeplatky, refundace, zrušení chybného přiřazení | Rozdělení jedné bankovní transakce mezi několik faktur |
| Banka | Normalizovaný CSV import, deduplikace, jednoznačné párování, ruční přiřazení | Konkrétní formát výpisu MONETA a přímé bankovní API |
| Upomínky | Tři stupně, nastavení, ruční/automatické SMTP, zastavení úhradou, pozastavení | Splátkové kalendáře, potvrzené doručení od poskytovatele |
| Náklady a odměny | Druh, příjemce, částka, datum, zaplacení | Schvalovací workflow, vzorce provizí, hromadné výplaty, přílohy účtenek |
| Reporty | Ceny, fakturace, příjmy, náklady, příspěvek před režií, konverze, zdroje, pohledávky a kapacita, CSV, měsíční graf čistých příjmů, kraje z webu | Vlastní grafy/reporty, uložené filtry, automatické rozesílky, regionální analýzy, reklamace |
| Předání | Záznam, příjemce, způsob, přesné verze finálních dokumentů | Elektronický podpis a klientské potvrzení převzetí |
| Archiv | Uzamčené pracovní podklady, minimálně 5 let, snapshot/ZIP/součty, bez podmínky fakturace či záznamu předání; finance nadále spravovatelné | Právní ověření dob uchování, samostatné lhůty dokumentových kategorií, řízená skartace |
| Zálohy | Stažení úplné zálohy, kontrolní součty, obnova do nové složky; denní místní záloha při běhu spouštěče, rotace 30 dní, vlastní cílový disk | Automatická oddělená záloha mimo PC/server, retenční politika záloh |
| Uživatelé | Individuální modelová práva, vlastní/přidělené/všechny zakázky, finance, export, interní dokumenty | Náhled jako uživatel a jemnější pravidla pro jednotlivá pole |
| Bezpečnost | Django autentizace, CSRF, ochrana přihlášení, MFA, soukromé soubory, audit, bezpečnostní hlavičky | Externí bezpečnostní revize a ověření celého produkčního nasazení |
| Windows / Android | Spouštěč, Waitress, mobilní rozhraní, domácí Wi-Fi | Skutečné ověření na zařízení majitele; veřejný HTTPS hosting |

## Externí předpoklady

- Skutečné odesílání vyžaduje bezpečně nakonfigurované SMTP. Žádné heslo není ve zdrojích a žádný skutečný e-mail při testech neodešel.
- Veřejná adresa vyžaduje hosting, doménu nebo přidělenou adresu a HTTPS. Dosud není nasazeno.
- Bankovní API vyžaduje poskytovatelem podporovaný přístup. Žádné bankovní přihlašovací údaje nejsou dostupné.
- Účetní a archivační pravidla musí před ostrým provozem odpovídat skutečnému režimu podnikatele.

## Provedená kontrola

- 82 automatických Django testů: workflow, platby, zálohy, bankovní duplicity, oprávnění, interní sdílení, MFA, archiv, formuláře, bezpečnostní hlavičky.
- Skutečné Chromium: přihlášení, hlavní obrazovky, mobilní velikost, PDF a absence horizontálního přetékání hlavní stránky.
- Skutečný Chromium průchod: založení zakázky → uložení předvyplněné faktury bez úprav → vystavení → přijetí platby → zelený stav Uhrazeno.
- Obsah PDF: česká diakritika, číslo, VS, účet a částka.
- Izolovaná souběžná kontrola: 12 zakázek a faktur přes 4 pracovní vlákna, bez duplicit a chyb na SQLite.
- Záloha: kontrolní součty a ověřená SQLite integrita obnovené databáze; příkaz obnovy do nové složky vyzkoušen.
- ARES, IMAP, SMTP a Windows úschova pověření jsou testované s náhradami. Skutečné služby ani skutečný Windows vault tím nejsou ověřené.
- Ověřen nový jednoduchý formulář faktury, doplnění klienta JavaScriptem včetně individuální splatnosti, kalendář s vlastní poznámkou a termínem zakázky, EML → poptávka a knihovna dokumentů ve skutečném Chromium.
- Upgrade kopie starší SQLite databáze zachoval počty klientů, zakázek a faktur i SHA-256 původních PDF. Integrita databáze zůstala v pořádku.

- 17 automatických testů skutečného webu, 6 společných testů web → CRM (včetně API/e-mail deduplikace, 10 příloh a odmítnutí nesprávného podpisu), Chromium všech tří formulářů se simulovaným SMTP. Žádná skutečná pošta nebyla odeslána.

- Nové browser ověření nabídka → uložené PDF → odmítnutí klientem, výběrový ZIP, report; obsah českého PDF nabídky i faktury ověřen pypdf. Přibalené DejaVu Sans s licencí pokrývá česká písmena včetně ě/ř/ů. Původní uložené PDF se nepřepisují. Denní záloha vytvořena reálným příkazem a všechny součty ZIP ověřeny.
