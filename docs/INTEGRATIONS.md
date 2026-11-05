# Poptávky z e-mailu a více webů

## Dvě možnosti provozu

1. **Windows bez veřejného serveru:** web odešle poptávku do vaší schránky, CRM ji přes šifrovaný IMAP stáhne. V přijaté poště zvolíte „Vytvořit poptávku“, nebo zapnete automatické vytváření pro vybranou složku. Počítač musí být zapnutý.
2. **Přímé napojení webu:** backend formuláře odešle podepsaný požadavek na veřejnou HTTPS adresu CRM. Každý web má vlastní zdroj, klíč a deduplikaci. Lokální adresa PC není z internetu dostupná a port se nemá zveřejňovat přes router.

Enepru.cz je přednastavený jako první zdroj. Další zdroj přidáte ve „Weby a zdroje poptávek“. Stačí název a doména; technický identifikátor se doplní. Samotné přidání záznamu ještě nenapojí existující formulář.

## Jednorázové připojení Seznam pošty na Windows

1. Aktualizujte CRM a spusťte jej alespoň jednou, aby se doinstalovaly knihovny.
2. Ve složce aplikace spusťte **Pripojit-postu.bat**.
3. Doplňte účet, složku pro příjem a heslo aplikace určené poskytovatelem pro IMAP/SMTP. Při psaní hesla nejsou vidět znaky.
4. Rozhodněte, zda chcete pouze načítat poštu, nebo ze všech zpráv zvolené složky automaticky zakládat poptávky. Doporučena je oddělená složka Poptavky; nikoliv automatický převod celého osobního INBOXu.
5. Restartujte CRM a v „Přijaté poště“ klikněte „Načíst poštu“. Odeslání otestujte kontrolovanou zprávou v „Odesílaných zprávách“.

Heslo se ukládá do Správce pověření Windows pod službou `LahodnyCRM.Mail`. Soubor `.mail-settings.json` obsahuje pouze ne-tajné nastavení a identifikátor pověření, nikdy heslo. Pokud systémové úložiště není dostupné, konfigurátor odmítne pokračovat; nemá textovou zálohu hesla. Vlastní úložiště na skutečném Windows zatím nebylo ověřeno; testy používají náhradní vault. Přihlášení ke skutečné schránce nebylo provedeno.

Průvodce používá šifrované IMAP 993 a SMTP SSL 465 pro Seznam. Poskytovatel musí povolovat zvolený způsob přihlášení. Hesla nevkládejte do chatu, CRM poznámek, GitHubu nebo běžných konfiguračních souborů.

## Příjem e-mailů

- Při prvním připojení se načte posledních 50 zpráv složky; potom pokračuje příjem nových zpráv po dávkách, bez duplicit.
- Používá se readonly výběr složky a BODY.PEEK; původní zprávy se nemažou, nepřesouvají a neoznačují jako přečtené.
- Bez připojení lze vložit soubor `.eml` a kliknout „Vytvořit poptávku“.
- Předvyplní se odesílatel, text, odhad služby a podporované přílohy. Chybějící adresa se doplní před nabídkou. Import nepředstírá, že adresu zná.
- Opakované kliknutí nevytvoří druhou poptávku.
- Odpověď na zprávu odeslanou z CRM se při shodném odesílateli a odkazu In-Reply-To/References přiřadí k existující poptávce. Čekající poptávka se vrátí k posouzení, nikoliv automaticky potvrdí.
- Přílohy odpovědi se doplní k poptávce a případné nearchivované zakázce. Uzamčený pracovní archiv se dodatečnou poštou nepřepisuje.
- HTML e-mailu se převádí na text. Nepovolené či příliš velké přílohy jsou uvedené jako přeskočené, ne tiše ztracené.

Vlastní tlačítko přímo v uživatelském rozhraní Seznam webmailu není součástí aplikace; k tomu by bylo potřeba rozšíření prohlížeče. Tlačítko je v přijaté poště CRM.

## Přímé API webu

Adresa pro Enepru: `POST /api/inquiries/enepru/`. Pro další web: `/api/inquiries/<identifikátor>/`. Historická adresa `/api/inquiries/` je alias Enepru.

Každý zdroj v CRM odkazuje na vlastní tajnou proměnnou prostředí, například `CRM_WEBHOOK_SECRET` pro Enepru a `CRM_WEBHOOK_DRUHY_WEB_KEY` pro další web. Hodnoty nastaví správce bezpečně na serverech CRM a webu; nikdy ne v JavaScriptu návštěvníka.

JSON:

```json
{
  "external_id": "a1d584fd-d00d-44a9-940b-c52de9078a6f",
  "name": "Ukázkový klient",
  "email": "klient@example.invalid",
  "phone": "+420 777 000 000",
  "address": "Ukázková 12, Praha",
  "service": "penb",
  "description": "Žádost o vyhotovení PENB",
  "requested_date": "2027-03-01"
}
```

Služby: `penb`, `passport`, `both`, `other`. `external_id` musí být UUID a pro opakovaný pokus téže poptávky zůstat stejné. Každý web má oddělený prostor identifikátorů.

Hlavičky:

- `X-CRM-Timestamp`: Unix čas v sekundách.
- `X-CRM-Signature`: hex HMAC-SHA256 nad přesnými bajty `timestamp + "." + JSON_body`, s klíčem příslušného webu.

Čas je platný pět minut. Při opakovaném doručení se vrátí existující záznam, při jiném obsahu se stejným ID konflikt 409. Úprava záznamu uvnitř CRM neporuší pozdější doručovací retry. Vrací se 201 při vytvoření, 200 při opakování, 400 při neplatných údajích, 403 při neplatném podpisu a 503 při chybějícím klíči. Zakázaný zdroj vrací 404. API samo neumožňuje nastavit stav potvrzeno nebo libovolného uživatele.

Napojení musí být v backendu skutečného webového formuláře; po selhání má zachovat požadavek a opakovat doručení. JSON podporuje `attachments`: seznam `{name, content, sha256}`, kde content je base64 a sha256 je kontrolní součet původního souboru. Nejvýše 10 souborů, 10 MB na jeden a 15 MB celkem. Lze přidat `source_details` s původní orientační kalkulací. Přímé API i strukturovaný e-mail používají stejný identifikátor a obsah pro deduplikaci.

## Skutečný stav napojení

- Podepisování, dvě nezávislé domény/klíče, replay, konflikty, převod EML, odpovědi a readonly IMAP byly otestovány izolovaně.
- Žádné skutečné heslo není v projektu a při testech nebyl odeslán skutečný e-mail.
- HTTPS kontrolu enepru.cz v cloudovém prostředí zablokoval proxy CONNECT 403. Potřebné domény byly přidány pouze do návrhu síťové konfigurace, nikoliv aktivovány.
- Skutečný zdroj je nyní dostupný v repozitáři Stano1988/enepru-web a byl upraven. Jde o vlastní Python aplikaci, nikoli WordPress. Šest společných testů ověřuje skutečný kód obou projektů. Nasazení změn na hosting a živé doručení zatím nejsou potvrzené.


## Připojení skutečného webu Enepru

**Windows bez veřejného CRM:** nasaďte změněný `app.py` i nový `crm_bridge.py` z enepru-web. Web dál odešle zprávu přes již nastavené SMTP. Přidává strojově čitelnou přílohu `enepru-poptavka.json`; nahrané podklady zůstávají běžnými přílohami. V CRM připojte schránku a vyberte složku pro poptávky. Rozpoznané formuláře webu se nově automaticky převedou na poptávky (CRM_IMAP_AUTO_WEB=1, výchozí). Běžná osobní zpráva zůstane v Poště s tlačítkem Vytvořit poptávku, pokud výslovně nezapnete převod celé složky.

Pro ověření původu vytvořte náhodný sdílený klíč (nejméně 32 znaků) v bezpečném nastavení hostingu jako `CRM_SHARED_SECRET`; na PC spusťte **Pripojit-web.bat**, ponechte `CRM_WEBHOOK_SECRET` a tentýž klíč vložte do skrytého vstupu. Uloží se do Správce pověření Windows. `.web-settings.json` obsahuje jen identifikátor, ne klíč. Restartujte CRM. Bez klíče lze strukturovaný e-mail importovat, ale jeho původ bude výslovně neověřený. Nesprávný podpis se odmítne. Starší dopisy webu bez metadat umíme rozpoznat podle shodného Reply-To a pole E-mail; také nejsou kryptograficky ověřené.

**Přímé HTTPS CRM:** na hostingu webu navíc nastavte `CRM_ENDPOINT` na skutečnou veřejnou adresu CRM s cestou `/api/inquiries/enepru/` a `CRM_SOURCE_SLUG=enepru`. Hodnotu nepřebírejte z adresy lokálního náhledu. Při nedostupnosti API web zkusí SMTP. Pokud není dostupné ani SMTP, uloží poptávku s přílohami do své SQLite fronty a uživateli pravdivě oznámí přijetí k pozdějšímu doručení (202). Server opakuje přenos, maximálně jednou za hodinu po opakovaných výpadcích. Fronta přežije restart a v administraci webu je vidět její počet. Po potvrzeném doručení se data fronty odstraní. Produkční záloha webu musí zahrnovat jeho SQLite databázi.

Další web dostane vlastní WebsiteSource, `CRM_SOURCE_SLUG` a vlastní klíč. Přímé API nevyžaduje SMTP, ale odpovědi a faktury z CRM ano. Windows lokální CRM nemusí mít otevřený port do internetu.

Podepsaná e-mailová metadata obsahují také seznam jmen příloh a jejich SHA-256. Změněný nebo chybějící soubor se odmítne před vytvořením poptávky.

## Přijatá i odeslaná složka a odpovědi

Nový průvodce Pripojit-postu.bat umí načítat i odeslané ze Seznamu (výchozí složka Sent). Stará nastavení je potřeba doplnit průvodcem nebo bezpečnými proměnnými CRM_IMAP_SYNC_SENT=1 a CRM_IMAP_SENT_FOLDER. Obě složky se čtou readonly a mají samostatné kurzory. Odeslané se nikdy automaticky nemění v nové poptávky. Native CRM zpráva a kopie stejného Message-ID v Sent jsou v seznamu jednou. Odpovědi z CRM používají In-Reply-To/References, e-maily lze ručně přiřadit a komunikace je přístupná i od zakázky/faktury. Podrobný rozsah a hranice synchronizace: [INTUITIVE-UPDATE.md](INTUITIVE-UPDATE.md). Skutečná schránka nebyla ověřena.
