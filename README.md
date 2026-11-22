# Music ID Tagger

Windows program DJ-könyvtárhoz. Mintát vesz a zenéből (Shazam), utána a Beatport v4 katalógusból hozza a BPM-et, a Camelot hangnemet és a DJ-stílust, például `Techno (Peak Time / Driving)`. Több mappát végigjár, és a tageket visszaírja MP3, FLAC, M4A, WAV, AIFF, OGG és Opus fájlokba.

A jelszó csak a futás idejére kerül a memóriába. A program nem menti el.

## Telepítés

1. Futtasd a `MusicIDTagger-Setup.exe` fájlt.
2. A Start menüben megnyílik a **Music ID Tagger**.
3. Adj hozzá mappákat. Az első kör **próba**: kiírja, mit találna, de nem nyúl a fájlokhoz.
4. Írd be a Beatport felhasználót és jelszót. A Spotifyhoz a [fejlesztői oldal](https://developer.spotify.com/dashboard) Client ID-ja és Client Secretje kell, nem a Spotify jelszavad. Vedd ki a pipát a próba elől, és indítsd újra.

A Beatport belépés ugyanaz a v4 út, amit a [beets-beatport4](https://github.com/Samik081/beets-beatport4) és a [kemo/beatport-api-client](https://github.com/kemo/beatport-api-client) használ: a docs oldal client azonosítója, session login, authorization code. Hivatalos partnerkulcs nélkül ez a működő megoldás. Ha a Beatport megváltoztatja az oldalt, a belépés eltörhet.

Az AcoustID kulcs nem kötelező. Csak akkor kell, ha a Shazam nem ismeri fel a számot, és van a gépen `fpcalc`.

A Spotify Web API client credentials belépést használ: `POST https://accounts.spotify.com/api/token`, utána `GET /v1/search` és `GET /v1/tracks/{id}`. Ebből jön az album, az év, az ISRC és a borító. A BPM-es `audio-features` végpont 2024. november 27. óta az új appoknak 403-at ad, ezért a BPM és a Camelot hangnem a Beatporttól marad. A Client Secret nincs elmentve.

## Mit ír a fájlba

- cím, előadó, album, év
- stílus a Beatport műfajából és alműfajából
- BPM
- hangnem Camelot formában (például `8A`), a zenei név a megjegyzésbe kerül
- kiadó, ISRC, Beatport ID, Spotify ID, mix neve
- borító, ha a fájlban még nincs

A „meglévő címet és előadót hagyja” pipa alapból be van kapcsolva. A Beatport BPM, hangnem és stílus találat esetén akkor is beíródik, ha a mező nem üres.

## Amit ebből raktam össze

| Feladat | Forrás |
| --- | --- |
| Hangfelismerés | [shazamio/ShazamIO](https://github.com/shazamio/ShazamIO) 0.9, Windows-on ffmpeg nélkül |
| Beatport BPM / hangnem / stílus | beets-beatport4 és kemo beatport-api-client |
| Spotify album / év / ISRC | hivatalos Spotify Web API, client credentials |
| Régebbi webes forrás | stevehero Mp3tag Beatport scriptjei. A kiadói oldalak tracklistája 2026-ban már nem megbízható, ezért nem arra épül |
| Tag írás | mutagen, Rekordbox-barát TKEY / TBPM / TPUB |
| Telepítő | PyInstaller onedir + Inno Setup 6. A natív Shazam könyvtár onefile exe-ben eltörik |
| Ha minden bolt kell | [OneTagger](https://onetagger.github.io/) már tud Discogsot, Spotifyt, Traxsource-t, Junót és Beatsource-t is. Ez a program a Shazam-mintára és a saját Beatport belépésre van kihegyezve |

## Saját fordítás

64 bites Python 3.12 kell. A `Python312-32` mappa 32 bites, arra a Shazam csomag nem települ.

```powershell
powershell -ExecutionPolicy Bypass -File .\build\build.ps1
```

A kész telepítő: `installer\Output\MusicIDTagger-Setup.exe`.
A GitHub Actions `windows-latest` futója ugyanezt megcsinálja minden `main` pushra.
