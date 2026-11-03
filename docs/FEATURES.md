# Stav požadavků

Tento soupis rozlišuje implementovanou funkci, provedenou kontrolu a nepřipojenou externí službu. Úplnou produkční připravenost netvrdíme.

| Oblast | Aktuální stav | Zbývající rozsah |
|---|---|---|
| Klienti a kontakty | Evidence, editace, kontaktní role, IČO/DIČ, dvě adresy | Řízené slučování duplicit, historie změn klienta, více firem u jednoho kontaktu |
| ARES | Načítací formulář, předvyplnění; test s mockovaným API | Skutečný přístup na ares.gov.cz je třeba ověřit v cílovém prostředí |
| Nemovitosti | Samostatná evidence, parcely, technické poznámky, vazba na zakázku | Podrobné strukturované odborné údaje a napojení na katastr |
| Webové poptávky | Formulář, přílohy, deduplikace opakovaného odeslání, potvrzovací e-mail ve frontě | Přesné napojení na skutečný web; distribuovaný antispam pro veřejný provoz |
| Nabídky | Verze, cena, rozsah, podmínky, platnost, e-mailový návrh, potvrzení klientem | PDF nabídky, automatická připomínka nezodpovězené nabídky, odmítnutí klientem přes odkaz |
| Zakázky | Převod, číslo, klient, nemovitost, termíny, popis, poznámky, historie, stav | Dílčí stavové workflow PENB/pasportu je nyní zastoupeno úkoly, nikoliv samostatnými stavovými kartami |
| Dokumenty | Složky, nahrávání, verze, metadata, přesun, koš, povolení uživatelé, soukromé stahování | Přetažení, interní náhled, hromadné operace a antivirový skener |
| Klientský přístup | Expirace, odvolání, nahrávání, požadavky, povolené finální výstupy | Klientský chat, volba termínu a potvrzení převzetí online |
| Termíny a práce | Úkoly, zaměření, začátek návštěvy, měsíční kalendář, hodiny, upozornění | Konflikty v kalendáři, automatické plánování kapacity, externí synchronizace |
| Vícepráce | Návrh, potvrzení odkazem, změna ceny a termínu, idempotence | Zamítnutí/revokace a přesné rozdělení do fakturačních položek |
| Faktury | Ze zakázky i samostatně, návrh, číslování, VS, PDF, QR, tisk, příprava e-mailu | Opravné doklady, externě vystavené faktury a jejich import, více záloh na jedno vyúčtování, další měny a DPH |
| Excelová předloha | Hlavní prvky, údaje dodavatele, české popisky a QR | Přesné grafické doladění proti původnímu souboru s majitelem |
| Platby | Ruční, částečné, přeplatky, refundace, zrušení chybného přiřazení | Rozdělení jedné bankovní transakce mezi několik faktur |
| Banka | Normalizovaný CSV import, deduplikace, jednoznačné párování, ruční přiřazení | Konkrétní formát výpisu MONETA a přímé bankovní API |
| Upomínky | Tři stupně, nastavení, ruční/automatické SMTP, zastavení úhradou, pozastavení | Splátkové kalendáře, potvrzené doručení od poskytovatele |
| Náklady a odměny | Druh, příjemce, částka, datum, zaplacení | Schvalovací workflow, vzorce provizí, hromadné výplaty, přílohy účtenek |
| Reporty | Ceny, fakturace, příjmy, náklady, příspěvek před režií, konverze, zdroje, pohledávky a kapacita, CSV | Grafy a vlastní reporty, uložené filtry, automatické rozesílky, regionální analýzy, reklamace |
| Předání | Záznam, příjemce, způsob, přesné verze finálních dokumentů | Elektronický podpis a klientské potvrzení převzetí |
| Archiv | Uzamčení rodiče i podřízených záznamů, snapshot, ZIP, součty, lhůta, blokace skartace | Právní ověření dob uchování, samostatné lhůty dokumentových kategorií, řízená skartace |
| Zálohy | Stažení úplné zálohy, kontrolní součty, obnova do nové složky | Automatická oddělená záloha mimo PC/server, retenční politika záloh |
| Uživatelé | Individuální modelová práva, vlastní/přidělené/všechny zakázky, finance, export, interní dokumenty | Náhled jako uživatel a jemnější pravidla pro jednotlivá pole |
| Bezpečnost | Django autentizace, CSRF, ochrana přihlášení, MFA, soukromé soubory, audit, bezpečnostní hlavičky | Externí bezpečnostní revize a ověření celého produkčního nasazení |
| Windows / Android | Spouštěč, Waitress, mobilní rozhraní, domácí Wi-Fi | Skutečné ověření na zařízení majitele; veřejný HTTPS hosting |

## Externí předpoklady

- Skutečné odesílání vyžaduje bezpečně nakonfigurované SMTP. Žádné heslo není ve zdrojích a žádný skutečný e-mail při testech neodešel.
- Veřejná adresa vyžaduje hosting, doménu nebo přidělenou adresu a HTTPS. Dosud není nasazeno.
- Bankovní API vyžaduje poskytovatelem podporovaný přístup. Žádné bankovní přihlašovací údaje nejsou dostupné.
- Účetní a archivační pravidla musí před ostrým provozem odpovídat skutečnému režimu podnikatele.

## Provedená kontrola

- 40 automatických Django testů: workflow, platby, zálohy, bankovní duplicity, oprávnění, interní sdílení, MFA, archiv, formuláře, bezpečnostní hlavičky.
- Skutečné Chromium: přihlášení, hlavní obrazovky, mobilní velikost, PDF a absence horizontálního přetékání hlavní stránky.
- Skutečný Chromium průchod: založení zakázky → uložení předvyplněné faktury bez úprav → vystavení → přijetí platby → zelený stav Uhrazeno.
- Obsah PDF: česká diakritika, číslo, VS, účet a částka.
- Izolovaná souběžná kontrola: 12 zakázek a faktur přes 4 pracovní vlákna, bez duplicit a chyb na SQLite.
- Záloha: kontrolní součty a ověřená SQLite integrita obnovené databáze; příkaz obnovy do nové složky vyzkoušen.
- ARES a SMTP v testech nahrazené mockem / paměťovým backendem. Skutečné služby tím nejsou ověřené.
