# Futtatás GitHub Codespaces-ben (akár csak telefonról)

## Első alkalommal

1. A repó oldalán: **Code → Codespaces → Create codespace on main**.
   Az első indítás néhány percig tart (Python, Chromium telepítése).
2. Nyisd meg a **Ports** fület (alul, vagy ☰ menü → View → Ports), és a
   **„Távoli asztal (bejelentkezéshez)” (6080)** sornál a földgömb ikonnal nyisd meg.
   Kattints a **Connect** gombra, jelszó: `lidlstat`.
3. A Codespace **Terminal**jába írd be:

   ```bash
   ./scripts/codespace-login.sh
   ```

   A távoli asztalon megnyílik egy böngészőablak a Lidl belépéssel. Lépj be
   (telefonszám/e-mail, jelszó, SMS-kód). Sikeres belépés után az ablak bezáródik,
   a token bekerül a `.env` fájlba, és a szerver újraindul.
4. A **Ports** fülön nyisd meg a **„Lidl statisztikák” (8000)** portot. Az első letöltés
   a blokkok számától függően pár percig tart, a fejlécben látod az állapotát.

A 8000-es port link privát: csak a GitHub-fiókoddal belépve nyílik meg. Mentsd el
könyvjelzőnek, vagy tedd ki a kezdőképernyőre.

## Később

- Ha a Codespace leállt (inaktivitás után magától leáll), indítsd újra a GitHubon
  (Code → Codespaces → a meglévő codespace). A szerver magától elindul, és letölti az új blokkokat.
- A token és az adatbázis (`.env`, `data/`) a Codespace-ben megmarad, amíg nem törlöd.
- Kézi újraindítás: `./scripts/codespace-start.sh`, napló: `/tmp/lidl-stats.log`.

Az ingyenes keret személyes fióknál havi kb. 60 óra (2 magos gépen).
Fölösleges futást elkerülhetsz, ha a GitHub beállításaiban rövid inaktivitási időt adsz meg
(Settings → Codespaces → Default idle timeout).
