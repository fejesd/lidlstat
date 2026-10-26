# Lidl statisztikák

Mobilra optimalizált webapp, ami a Lidl Plus blokkjaidból statisztikákat készít:

- havi költés, vásárlások száma, átlagos kosárérték, kuponokkal/kedvezményekkel megtakarított összeg
- mikor vásárolsz (nap × óra hőtérkép)
- top termékek összeg vagy gyakoriság szerint
- árfigyelő: egy termék egységárának alakulása (súlyos áruknál Ft/kg)
- boltok és a blokkok tételes listája

A háttérben egy FastAPI szerver letölti a blokkokat egy helyi SQLite adatbázisba, a felület
egy egyszerű HTML + [Chart.js](https://www.chartjs.org/) oldal, ami a telefonon a kezdőképernyőre
is kitehető.

> **Figyelem:** a Lidl Plus API nem hivatalos, visszafejtett végpontokat használ, és bármikor
> megváltozhat. Csak a saját fiókod adataihoz használd.

## 1. Refresh token megszerzése (egyszer)

A Lidl bejelentkezését reCAPTCHA védi, ezért egy valódi böngészőablakban kell belépned. Ezt a
saját gépeden futtasd (nem a szerveren / Docker konténerben):

```bash
uv sync
uv run --extra login playwright install chromium   # csak első alkalommal
uv run --extra login lidl-stats-login --env-file .env
```

Megnyílik egy Chromium ablak: lépj be a Lidl Plus fiókodba (telefonszám/e-mail, jelszó, SMS/e-mail kód).
Sikeres belépés után az ablak bezáródik, és a token bekerül a `.env` fájlba.

**Böngésző-automatizálás nélkül** (`--manual`): kiír egy linket, amit bármelyik asztali böngészőben
megnyithatsz. Nyisd meg előtte a Fejlesztői eszközök > Network fülét („Preserve log” bekapcsolva).
Belépés után a böngésző egy `com.lidlplus.app://callback?code=...` címre próbál átirányítani,
ami hibát ad, és ez így rendben van. Ezt a címet másold vissza a terminálba.

A token hosszú ideig érvényes. Ha a Lidl megújításkor újat ad, az app automatikusan elmenti az
adatbázisba. Ha egyszer mégis lejár, futtasd újra a login parancsot, és indítsd újra a konténert.

## 2. Futtatás Dockerrel

```bash
cp .env.example .env     # ha még nincs; a LIDL_REFRESH_TOKEN legyen kitöltve
docker compose up -d --build
```

Utána a telefonodon nyisd meg a `http://<szerver-ip>:8000` címet, és tedd ki a kezdőképernyőre
(iOS Safari: Megosztás > Főképernyőhöz adás, Android Chrome: menü > Hozzáadás a kezdőképernyőhöz).

Az első indításkor letölti az összes blokkot (ez pár percig is eltarthat), utána
`SYNC_INTERVAL_HOURS` óránként csak az újakat. A jobb felső gombbal kézzel is frissíthetsz.
Az adatbázis a `./data` mappába kerül.

Ha nem csak otthoni hálózaton (pl. VPN-en vagy reverse proxy mögött) éred el, állíts be egy
`APP_TOKEN`-t. Ekkor a webapp első megnyitáskor elkéri a kódot. A proxy mögött mindenképp HTTPS-t használj.

## Futtatás GitHub Codespaces-ben

Ha nincs saját géped vagy szervered (akár csak telefonról is): lásd [CODESPACES.md](CODESPACES.md).

## Beállítások (`.env`)

| Változó | Alapérték | Leírás |
|---|---|---|
| `LIDL_REFRESH_TOKEN` | – | a login paranccsal szerzett token |
| `LIDL_COUNTRY` / `LIDL_LANGUAGE` | `HU` / `hu` | ország és nyelv |
| `TIMEZONE` | `Europe/Budapest` | erre az időzónára számolja a napokat/órákat |
| `SYNC_INTERVAL_HOURS` | `6` | automatikus frissítés gyakorisága, `0` = ki |
| `APP_TOKEN` | üres | opcionális hozzáférési kód az `/api` végpontokhoz |
| `LIDL_APP_VERSION` | `16.45.5` | az API elutasítja a valótlan app verziókat; ha hibát kapsz, emeld |
| `DB_PATH` | `data/lidl.sqlite3` | SQLite fájl helye (Dockerben `/data/lidl.sqlite3`) |

## Ha a tételek nem jók

A blokkrészleteket a Lidl HTML-ként adja vissza, a formátuma nincs dokumentálva, és országonként
eltérhet. Az elemző a `data-art-*` attribútumokból olvas, a negatív összegű sorokat pedig az előző
tétel kedvezményének veszi. Az app minden blokk nyers válaszát eltárolja, és jelzi
(„⚠ ellenőrizendő”), ha a tételek összege nem egyezik a végösszeggel. Ilyenkor:

1. a blokk lenyitásakor a „Nyers adat megnyitása” linken (`/api/receipts/<id>/raw`) megnézheted a választ,
2. javítsd a `src/lidl_stats/parser.py`-t,
3. futtasd a `lidl-stats-sync --reparse` parancsot (Dockerben
   `docker compose exec lidl-stats lidl-stats-sync --reparse`). Ez letöltés nélkül újraelemzi a tárolt blokkokat.

Egyéb parancsok: `lidl-stats-sync` (új blokkok letöltése), `lidl-stats-sync --full` (minden
blokk újratöltése).

## Fejlesztés

```bash
uv sync
uv run lidl-stats          # http://localhost:8000
uv run pytest
uv run mypy
uv run ruff check . && uv run ruff format --check .
```

| Fájl | Szerep |
|---|---|
| `src/lidl_stats/lidl_client.py` | Lidl Plus API kliens (token megújítás, blokklista, blokkrészletek) |
| `src/lidl_stats/parser.py` | blokkrészletek (HTML / JSON) tételekre bontása |
| `src/lidl_stats/db.py` | SQLite séma, mentés, újraelemzés |
| `src/lidl_stats/sync.py` | letöltés (inkrementális), refresh token kezelés |
| `src/lidl_stats/stats.py` | statisztikai lekérdezések |
| `src/lidl_stats/main.py` | FastAPI végpontok + statikus felület |
| `src/lidl_stats/login.py` | egyszeri bejelentkezés |
| `src/lidl_stats/static/` | a mobil webapp |
