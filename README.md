# Lahodný CRM

Vývojový základ CRM pro PENB a pasporty. Django 5.2, SQLite, serverové HTML.

## Spuštění pro vývoj

Z kořene repozitáře (existující checkout; nevytvářet další worktree):

```sh
python -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python manage.py migrate
.venv/bin/python manage.py createsuperuser
CRM_DEBUG=1 .venv/bin/python manage.py runserver 127.0.0.1:8000
```

Správce si při `createsuperuser` zvolí vlastní přihlašovací údaje. Žádné výchozí heslo není vytvořeno. Pro lokální funkční kontrolu otevřít `/accounts/login/`, založit klienta a zakázku. Statické soubory ve vývoji obsluhuje runserver při CRM_DEBUG=1.

```sh
.venv/bin/python manage.py test
.venv/bin/python manage.py check
```

## Co funguje

- Přihlášení a odhlášení přes Django, CSRF ochrana.
- Správce zakládá klienty a zakázky, přiděluje uživatele.
- Pracovník s příslušnými modelovými právy vidí jen přidělené zakázky a jejich klienty.
- Čísla od Z27/001, klient, služba, adresa, termín, stav, další krok.
- Přehled, hledání a filtr stavu, označení prodlení.
- Popis, historie změn a průběžné poznámky s autorem.

Uživatelům bez práv není zpřístupněna žádná pracovní agenda. Přidělování a založení zakázky je v první verzi pouze pro superuživatele. Jemnější oprávnění, soubory, nabídky, faktury, QR, odesílání e-mailů, platby, automatizace a archiv dosud nejsou implementované.

## Data a provoz

SQLite `db.sqlite3` a `.local-secret` nejsou v Gitu. Tajný klíč se pro vývoj vytvoří lokálně; v produkci použít CRM_SECRET_KEY ze správce tajných údajů. Nesmazat klíč při restartu. Smazání databáze smaže data i přidělené pořadí.

Toto není nasazení připravené na osobní údaje skutečných klientů. Před produkcí doplnit PostgreSQL pro víceuživatelský provoz, HTTPS (`CRM_HTTPS=1`), CRM_ALLOWED_HOSTS, produkční WSGI server, statické soubory, omezení pokusů o přihlášení, MFA, zálohy a ověřit obnovu. Nezpřístupňovat vývojový server veřejně. Souběžné číslování zakázek používá transakci; na PostgreSQL je potřeba doplnit zámek řádku a otestovat souběh, zatím není produkčně ověřené.

Dodavatel: Ing. Stanislav Lahodný, Pikárec 119, 592 53 Pikárec, IČO 21639108, neplátce DPH. E-mail penb.lahodny@seznam.cz, MONETA Money Bank, účet 267467312/0600. Tyto údaje jsou zatím specifikací pro budoucí fakturaci, nikoliv hotovou fakturační funkcí.
