# Pokračování práce — 3. 11. 2026

## Aktuální požadavek uživatele

Nyní práci přerušit, uložit kontext a příště pokračovat. Priorita příštího sezení: umožnit majiteli aplikaci skutečně prohlížet a ovládat. Neslibovat běh práce na pozadí mezi sezeními.

## Projekt a ověřený stav

Repozitář /workspace/Enepru---CRM-Faktury byl prázdný, bez commitů. Vytvořen Django 5.2.18 projekt, SQLite, české serverové HTML, responzivní CSS. Zdrojové soubory dosud nejsou commitnuté; neodstraňovat je. Podrobnosti README.md a ROADMAP.md.

Implementováno: přihlášení/odhlášení, Django správa účtů a modelových práv, založení a seznam klientů, založení/seznam/detail/úprava zakázky, hledání a filtr stavu, termín a prodlení, odpovědný pracovník, další krok, popis s historií změn, interní poznámky s autorem a časem. Nesprávce s potřebným oprávněním vidí pouze přidělené zakázky a jejich klienty. Zakládání a přidělování zakázek pouze správce. Jemná oprávnění ještě nejsou dokončená.

Prošlo 6 Django testů, system check a kontrola migrací. Skutečný HTTP požadavek na login i CSS vrátil 200 a očekávaný obsah. Žádný správce ani výchozí heslo nejsou vytvořené. Lokální databáze obsahuje pouze migrace, testovací data se po testech odstranila. Nezaměňovat funkční vývojový základ za kompletní CRM nebo produkční nasazení.

Vývojový server byl spuštěn na 127.0.0.1:8000; proces nemusí přežít přerušení. Sandbox pro síť a naslouchání vyžadoval require_escalated. Standardní Git proxy funguje při eskalaci, git ls-remote vrátil úspěch bez refs (prázdný remote).

Install_script a start_skill uloženy do draftu cloud prostředí. Nástroj potvrdil status saved, requires_publish=true. Uživatel byl informován o potřebě kontroly, uložení a publikace. Publikace nebyla potvrzena.

## Možnosti prohlížení — vyřešit před dalšími rozsáhlými funkcemi

Onboarding skill zakazuje uživatelské localhost preview odkazy, UI tohoto prostředí je nepodporuje. Neříkat, že aplikaci nelze používat obecně: omezení se týká přímého náhledu této cloudové mašiny. Nezveřejňovat DEBUG server ani nepoužívat tunel k obcházení síťové politiky.

Možnost A: bezpečně exportovat aktuální zdrojové soubory jako ZIP bez .venv, db.sqlite3, .local-secret, hesel a tajných údajů. Uživatel může spustit CRM na vlastním PC s Pythonem a vytvořit vlastní účet; localhost bude pak na jeho PC. Případně připravit jednoduché spouštěcí skripty pro jeho OS, až bude znám.

Možnost B: soukromé testovací nasazení s HTTPS, DEBUG=0, správně omezenými hosty, produkčním WSGI serverem, statickými soubory, bezpečným účtem a přístupem. Nejprve ověřit dostupný hosting a oprávnění k nasazení; nevymýšlet veřejnou URL ani tvrdit nasazení bez důkazu. Před reálnými klientskými daty doplnit ochranu přihlášení, MFA, zálohy a obnovu, granulární práva a produkční databázi.

Příště nejprve zjistit, zda chce uživatel lokální spuštění (a jeho OS), nebo dostupný hosting. Lze nezávisle připravit export a provozní dokumentaci. Žádné přístupové údaje nevyžadovat do chatu.

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
