# Zjednodušené CRM podle posledních připomínek

## Menu v pořadí práce

Pošta (Přijatá / Rozepsaná / Odeslaná) → Klienti → Poptávky a nabídky → Zakázky (Přehled / Archiv) → Faktury (Přehled / Nastavení faktur) → Dokumenty → Kalendář → Reporty → Nastavení a další možnosti.

Barvy vycházejí ze současného Enepru webu: modrá #253b50/#304c66, světlé pozadí #fcfaf6 a měděné akcenty. Zelená zůstává pro zaplacení. Technické nastavení, zdroje webů, bankovní import a starší agendy nejsou v hlavním pracovním postupu.

## Poptávka až k penězům

1. Poptávka přenesená z webu obsahuje kontakt, adresu, přílohy a kalkulaci. Klikni **Odpovědět**.
2. Otevře se e-mail „Děkujeme za Vaši poptávku… cena… prosíme o potvrzení“. Cena je z kalkulačky, termín lze změnit. Při úpravě ceny/termínu se v připraveném textu aktualizuje příslušná věta. Odeslání je vždy výslovné; bez SMTP se uloží návrh. Také předvyplněný e-mail s fakturou lze odeslat přímo z jeho editoru bez přechodu do jiné agendy.
3. Po potvrzení zákazníkem e-mailem klikni **Zákazník potvrdil nabídku**, zkontroluj fakturační adresu a ulož potvrzení. Nejde o automatické přijetí podle pouhého příchodu e-mailu.
4. Klikni **Vytvořit zakázku**. Cena, adresa a fakturační údaje se převezmou. Přílohy jsou přímo u zakázky.
5. **Přidat podklady** nabízí pouze výběr souborů; lze více najednou (5 / 25 MB). Název souboru otevře PDF/obrázek, vedle je **Stáhnout**. Ostatní typy se stáhnou. Starší správa verzí a složek je v dalších možnostech.
6. **Vytvořit fakturu** převezme cenu a klienta. Formulář zůstává jednoduchý: text a jedna částka. Podoba PDF se řídí excelovou předlohou majitele.
7. Až dorazí peníze, klikni **Označit jako zaplacenou**, zkontroluj datum a potvrď. Zbývající částka se předvyplní a upomínky se zastaví. Částečná úhrada je dostupná odkazem. Bankovní připojení není potřeba.

Pokud kalkulačka uvádí cenu na dotaz, CRM si cenu nevymýšlí. Při kombinaci PENB + pasport se číselná cena PENB předvyplní, ale formulář upozorní, že je potřeba doplnit cenu pasportu, protože web ji do součtu dosud nezahrnuje. Cena nabídky není automaticky potvrzená zákazníkem.

## Jednodušší zakázka a klient

U PENB stačí adresa nemovitosti, není nutné zakládat kartu Nemovitosti. Staré karty zůstávají zachované. Kontrola požadovaných podkladů se už nevytváří ani nezobrazuje. Úkoly, historie, náklady, klientské odkazy a archivace jsou rozbalovací. Již uložené doklady a archiv se nepřepisují.

Karta klienta ukazuje především kontakt, fakturační adresu a poznámky. Firemní údaje, jiná splatnost a korespondenční adresa jsou nepovinné rozbalovací údaje. Oprávnění mají české názvy a podrobný seznam činností je také rozbalovací.

Záhlaví seznamů mají šipky. Kliknutí střídá vzestupné/sestupné řazení a zachovává filtry. Týká se poptávek/nabídek, klientů, zakázek, archivu, faktur, dokumentů a pošty; dostupné jsou sloupce dané agendy. Faktury lze řadit i podle vypočteného zůstatku a stavu.

## Faktura z původní XLSM předlohy

`assets/invoice/template.json` je odvozený z dodaného **Faktura moje +QR_Macro.xlsm**: skutečné šířky sloupců, výšky řádků, slučování buněk, rámečky, písma a popisky. PDF má jednu A4. Údaje původního odběratele, jeho položky a staré částky v distribuční předloze nejsou. Makra se nespouštějí a původní QR se nepoužívá; nový QR vzniká podle konkrétní faktury.

Na Windows se použije nainstalovaný Arial odpovídající původnímu souboru. Kde Arial není, je přibalená metrická náhrada Liberation Sans s licencí. Pixelově totožný tisk z Excelu na skutečném Windows zatím nebyl porovnán; ukázka výsledného PDF je v `docs/screenshots/faktura-podle-sablony.png`. Delší text se zalomí v oblasti položek. Šablona dovoluje 14 řádků (12 při odečtu zálohy); běžný formulář používá jeden volný text. Uložené dříve vystavené PDF se při aktualizaci nemění.

## Pošta přijatá i odeslaná ze Seznamu

Rozpoznané formuláře webu se po načtení přijaté pošty automaticky převedou na poptávky (CRM_IMAP_AUTO_WEB=1 je výchozí). Běžný osobní e-mail se bez kliknutí nepřevádí; hromadný převod všech zpráv je zvláštní výslovná volba.

V **Pripojit-postu.bat** lze zapnout také načítání odeslané složky. Pro Seznam je předvyplněná **Sent**; skutečný název je nutné ověřit ve schránce. Restartuj CRM a klikni **Načíst poštu**. Stará konfigurace zůstává funkční; pro přidání odeslané složky spusť průvodce znovu. Heslo patří do skrytého vstupu průvodce, nikoli do chatu.

Přijatá a odeslaná složka mají samostatné kurzory, readonly SELECT a BODY.PEEK. CRM původní zprávy nemaže, nepřesouvá ani neoznačuje jako přečtené. Při prvním připojení se z každé složky načte posledních 50 zpráv, dále nové po dávkách. Nejde o import celého historického archivu schránky. Zpráva nad 25 MB vyžaduje ruční vyřešení; tato kontrola se nesmí tiše vydávat za úplný import.

Odeslaná pošta kombinuje zprávy z CRM a importované zprávy ze Sent. Kopie stejného Message-ID se nezobrazuje podruhé. E-maily lze přiřadit k poptávce nebo zakázce a odpovídat přímo z jejich detailu. Odpovědi používají In-Reply-To/References; vlákna se propojují podle identifikátorů a odpovídajícího kontaktu, nikoli podle pouhé podobnosti předmětu. Odpověď na fakturu je propojená i s fakturou. Na zakázce je rozbalovací Komunikace.

Tato funkce kopíruje přijaté a odeslané zprávy do CRM a dovoluje odesílání přes SMTP; nejde o obousměrné zrcadlení mazání, složek či příznaků. CRM neukládá vlastní SMTP zprávy do Sent přes IMAP APPEND; zda je tam uloží poskytovatel, záleží na schránce. Odeslané z CRM jsou vždy v jeho vlastní historii.

Živá schránka není připojená; funkce prošly náhradou IMAP/SMTP. Průvodce Windows s keyring není na skutečném zařízení majitele ověřený. Pro provoz musí být PC i CRM zapnuté; automatická kontrola běží přibližně každých 5 minut.

## Kontrola a aktualizace

96 Django testů, šest společných testů přenosu z webu a skutečný Chromium průchod celého zjednodušeného postupu včetně mobilního menu. Testy pošty ověřují obě složky, samostatné kurzory, žádné mazání, návaznost odpovědí a deduplikaci odeslaných. PDF prošlo textovou i vizuální kontrolou, jedna A4. Kopie starší databáze zachovala počty záznamů a SHA-256 původních PDF. Žádná skutečná pošta se neposílala.

Při aktualizaci zachovej původní databázi, media, .local-secret a poštovní/webové nastavení. Účet znovu nezakládej. Nové migrace jsou 0024–0026. Další rozsahy původního projektu jsou stále popsané v FEATURES.md; tento dokument neprohlašuje celé rozšířené zadání za dokončené.
