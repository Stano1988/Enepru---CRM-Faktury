# Pokračování práce — aktuální stav 3. 11. 2026

## Pokyn uživatele

Majitel chce dokončit celé CRM podle konverzace, ne pouze vizuální prototyp. Poslední instrukce: pokračovat a doplnit vše. Má Windows a Android a chce jednoduché bezplatné prohlížení. Nemusí zadání opakovat. Neříkat, že je hotové celé zadání, dokud zbývají položky v FEATURES.md.

## Aktuální implementace

Django 5.2.18, SQLite s IMMEDIATE transakcemi, Waitress a WhiteNoise. Spouštěče Windows automaticky připraví databázi, soubory a účet; žádné výchozí heslo. Responzivní mobilní menu. Aplikace je stále pracovní verze bez veřejného hostingu.

Fungují klienti/kontakty/nemovitosti, poptávky z formuláře s přílohami, verzované nabídky, klientské potvrzení a převod na zakázku, dokumenty a verze/koš/sdílení, klientské odkazy, úkoly a měsíční kalendář, vícepráce, fakturační návrhy/PDF/QR, zálohová výzva a jedno zálohové vyúčtování, úhrady/refundace, oprava chybného přiřazení, CSV banky, příprava upomínek, e-mailová fronta, náklady, reporty, předání, archiv se snapshotem a kontrolními součty, zálohy a obnova, uživatelská práva a MFA.

Přesný stav, nedodělané funkce a externí předpoklady jsou v docs/FEATURES.md. Není připojené skutečné SMTP ani bankovní API a není nasazeno na veřejné adrese. ARES je připravený, testovaný pouze mockem. Windows/Android zařízení majitele zatím neověřeno.

## Kontroly

40 automatických testů, kontrola Django a migrací. Skutečný Chromium desktop i mobilní rozměr, přihlášení a funkční průchod zakázka → předvyplněná faktura → vystavení → úhrada. České PDF zkontrolováno přes pypdf. 12 souběžných zakázek/faktur v izolované SQLite bez duplicit. Ověřená záloha a obnova do nové složky. Nástroje pro browser/PDF/lint jsou v /tmp/crm-review-tools, nejsou běhovými závislostmi aplikace.

Při browser kontrole byly nalezeny a opraveny dvě chyby: hlavička Referrer-Policy no-referrer bránila HTTP loginu (používá se same-origin); předvyplněné extra řádky faktury byly při POST považovány za prázdné (initial se předává pouze na GET). Mají regresní testy. Při změnách fakturačního formuláře znovu zkontrolovat skutečný browser.

Ukázkové screenshoty v docs/screenshots obsahují pouze smyšlené klienty. Kontrolní databáze /tmp/crm-review.sqlite3 je oddělená od aplikace. Kontrolní účty/hesla nepatří do Gitu ani do zpráv uživateli. Do hlavní lokální databáze nebyl založen správce ani vložena demo klientská data.

## Další postup

1. Navázat podle nedokončených položek FEATURES.md, zejména opravné doklady/import externích faktur, nabídka PDF a připomínky, pokročilé reporty a oprávnění.
2. S majitelem ověřit instalaci na Windows a Android; případně připravit soukromý HTTPS hosting. Nezaměňovat GitHub se spuštěnou aplikací, nevymýšlet veřejnou URL.
3. SMTP nastavit bezpečně v cílovém prostředí. Hesla nechtít do chatu. Konkrétní bankovní formát/API ověřit až s dostupnými podklady.
4. Před ostrými daty uzavřít bezpečnostní, účetní a archivační ověření a oddělené automatické zálohy.

Uživatel autorizoval ukládání a odesílání projektu na GitHub main. Žádné force-push. Zachovat lokální databázi, media a .local-secret; nejsou sledované v Gitu. Cloudové instalační a startovací instrukce jsou v návrhu prostředí; publikaci provádí uživatel, nebyla potvrzena. Používat existující checkout, nevytvářet worktree.

## Dokumentace

README.md, docs/WINDOWS.md, docs/OPERATIONS.md, docs/FEATURES.md. Informace z původní domluvy následují níže; při rozporu o implementaci platí aktuální FEATURES.md a skutečný kód.

## Závazné požadavky majitele

- CRM pro PENB a pasporty; celý řetězec webová poptávka → nabídka s cenou a termínem → potvrzení klientem → zakázka → práce → kontrola → předání → faktura → úhrada → archiv.
- Zadávat jednou, údaje automaticky přenášet.
- Zakázky od roku 2027, formát Z27/001. Chování přes další rok potvrdit; současný kód resetuje řadu podle roku, minimum 2027.
- Faktury samostatná řada PF 26013 (současný vzor); skutečné poslední číslo a přechod do 2027 ověřit.
- VS faktur ze zakázky obsahuje základ zakázky + pořadí dokladu, např. 2700101. Bez zakázky podle čísla faktury. Před realizací ověřit kolize, pevné délky, max. 10 číslic.
- Faktury také bez zakázky za jiné služby; doplnění externě vystavených dokladů bez duplicit.
- Kliknutí na přípravu faktury otevře předvyplněný návrh, uživatel upraví, vystaví, vytiskne, označí vytištěno, odešle. Sledovat splatnost, upozornit na prodlení, upomínky, po úhradě zelený stav s textem. Číslo až při vystavení. Tisk nelze automaticky spolehlivě potvrdit prohlížečem.
- PDF podle XLSM, QR české platby z aktuálního účtu/částky/VS. Žádná závislost na Excel makrech.
- U zakázky termín vyhotovení, popis doplňovaný od založení i průběžně, poznámky s historií.
- Všechny podklady přímo u zakázky: složky, nahrávání, přesun, přejmenování, stažení, verze, koš, řízení přístupu, přílohy z poptávky přenést.
- Archiv pro případ kontroly, požadováno 5 let. Ověřit právní lhůty podle dokumentu a počáteční událost, účetní doklady zvlášť. Archiv chráněný, exportovatelný, zálohy samostatně.
- Majitel individuálně rozhoduje co uživatel vidí a dělá, včetně finančních polí, dokumentů, exportů a vlastních/přidělených/všech zakázek. Serverová kontrola, ne pouze skryté menu.
- Klienti, kontakty, nemovitosti samostatně; objednatel/vlastník/fakturační subjekt/kontakt pro vstup mohou být různí.
- PENB + pasport jedna zakázka s dílčími částmi a vlastními termíny.
- Nabídky s verzemi a důkazem potvrzení, vícepráce schvalované, podklady kontrolované, interní a klientské termíny oddělené.
- Kalendář, zaměření, mapa výjezdů, úkoly, kapacita, čas, doprava a náklady.
- Externí odměny a provize, stav schválení a úhrady, výnosnost.
- Platby ruční/import/banka, částečné, přeplatky, nejasné shody ručně, duplicity zakázat.
- Automatizace s historií, vypnutím, schvalováním a idempotencí. Upomínky zastavit při platbě nebo sporu.
- Reporty obchodu, zdrojů, konverzí, termínů, kapacity, zakázek, příjmů, fakturace, pohledávek, nákladů, výnosnosti a archivu. Potvrzené ceny, vystavené faktury a přijaté platby vykazovat zvlášť.
- Profesionální české responzivní prostředí, bezpečnost, zálohy a ověřená obnova.

## Dodavatel a podklady

Ing. Stanislav Lahodný, Pikárec 119, 592 53 Pikárec, IČO 21639108, neplátce DPH.
E-mail penb.lahodny@seznam.cz. MONETA Money Bank, účet 267467312/0600.
Údaje převzaty z uživatelova vzoru a potvrzeny v konverzaci; nejsou to přihlašovací tajné údaje.
Excel: /workspace/attachments/d29080ae-d82d-4535-8065-ec0faa872502/Faktura moje +QR_Macro.xlsm
Sediment ID file_0000000027fc81f789447c510901527b.
Makra nebyla spuštěna. Obsah buněk prohlédnut přes ZIP/XML.
Uživatel dodal screenshoty SugarCRM: klient, adresář, seznam a detail zakázky, reporty, platby, dokumenty/archiv, role a uživatelské menu. Použít jako funkční inspiraci, ne kopírovat zastaralé rozhraní.

## Nejbližší implementace po vyřešení prohlížení

Samostatné nemovitosti a role kontaktů, editace klienta, dokumenty u zakázky, poptávky a nabídky, faktura/PDF/QR, úhrady a upomínky, archiv. Dodržovat pravdivé vymezení hotových funkcí. Před produkcí vyřešit souběžné číslování na PostgreSQL, přístupová práva a zálohy.
