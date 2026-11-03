# Lahodný CRM

- Před prací přečti docs/CONTINUE.md a docs/FEATURES.md. Zachovej celé uživatelské zadání a aktualizuj stav funkcí po změnách.
- Používej existující checkout. Nevytvářej worktree bez výslovného požadavku.
- Nikdy necommituj db.sqlite3, media/, .local-secret, zálohy nebo skutečná hesla. Nevytvářej výchozí heslo správce.
- Nezaměňuj GitHub ani lokální cloudový port za veřejně dostupné CRM.
- Vystavené doklady, archiv a finanční historie se nesmí zpětně tiše přepisovat.
- Oprávnění kontroluj serverově a při každém novém endpointu ověř cizí zakázku, soubor a finanční data.
- Pro změny workflow použij `.venv/bin/python manage.py test`, `check` a `makemigrations --check --dry-run`.
- Při změně předvyplněných formulářů ověř jejich skutečné odeslání, ne pouze stav GET.
- Windows spouštěče zachovej a nepožaduj po majiteli obsluhu vývojového prostředí, je-li možný jednoduchý spouštěč.
- Buď přesný o implementaci, skutečném ověření služeb a produkční připravenosti. Nepiš, že je vše hotové, pokud FEATURES.md obsahuje zbývající požadavky.
