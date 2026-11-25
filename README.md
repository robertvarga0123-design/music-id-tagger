# Music ID Tagger

Windows program DJ-könyvtárhoz. Mintát vesz a zenéből (Shazam), utána a Beatport v4 katalógusból hozza a BPM-et, a Camelot hangnemet és a DJ-stílust, például `Techno (Peak Time / Driving)`. A Deezer, az Apple, a MusicBrainz és a Discogs kulcs nélkül tölti ki az albumot, az évet, az ISRC-t vagy a kiadót. Több mappát végigjár, és a tageket visszaírja MP3, FLAC, M4A, WAV, AIFF, OGG és Opus fájlokba.

## Mi kell hozzá

- Beatport fiók: felhasználónév és jelszó. Ebből jön a BPM, a Camelot hangnem és a DJ-stílus.
- Spotify kulcs: opcionális. A [fejlesztői oldal](https://developer.spotify.com/dashboard) Client ID-ja és Client Secretje kell, nem a Spotify jelszó. Album, év, ISRC.
- A többi katalógus kulcs nélküli: Deezer, Apple, MusicBrainz, Discogs.
- AcoustID kulcs nem kötelező. Csak akkor, ha a Shazam nem ismeri fel a számot, és van a gépen `fpcalc`.
- Grok és Gemini kulcs opcionális, csak a bizonytalan találatokhoz. [console.x.ai](https://console.x.ai) és [aistudio.google.com](https://aistudio.google.com).
- Webes keresés alapból ki van kapcsolva.

## Telepítés

1. Futtasd a `MusicIDTagger-Setup.exe` fájlt.
2. A Start menüben megnyílik a **Music ID Tagger**.
3. Adj hozzá mappákat. Az első kör **próba**: kiírja, mit találna, de nem nyúl a fájlokhoz.
4. Írd be a Beatport felhasználót és jelszót. Vedd ki a pipát a próba elől, és indítsd újra.

A jelszó és a kulcsok ezen a gépen maradnak, a Windows DPAPI titkosításával. Üres mező nem törli a mentettet. A „Ne jegyezze meg a jelszavakat” pipa kitörli őket. Parancssorban a `MIT_BEATPORT_PASS` és a `MIT_SPOTIFY_SECRET` környezeti változót használd: a `--beatport-pass` és a `--spotify-secret` látszik a folyamatlistában.

A Beatport belépés ugyanaz a v4 út, amit a [beets-beatport4](https://github.com/Samik081/beets-beatport4) és a [kemo/beatport-api-client](https://github.com/kemo/beatport-api-client) használ. Hivatalos partnerkulcs nélkül ez a működő megoldás.

A Spotify Web API client credentials belépést használ. A BPM-es `audio-features` végpont 2024. november 27. óta az új appoknak 403-at ad, ezért a BPM és a Camelot hangnem a Beatporttól marad.

## Mit ír a fájlba

- cím, előadó, album, év
- stílus: a már kitöltött műfajt csak a Beatport írja felül. Üres mezőbe más forrás is írhat, ha a címke nem általános (`Dance`, `Pop`, `Electronic`, `Electronica`, `Music`)
- BPM. A már bent lévő, nem változó tizedes BPM-et nem kerekíti át
- hangnem Camelot formában (például `8A`), a zenei név a megjegyzésbe kerül
- kiadó, ISRC, Beatport ID, Spotify ID, mix neve
- borító, ha a fájlban még nincs

A „meglévő címet és előadót hagyja” pipa alapból be van kapcsolva. A Beatport BPM, hangnem és stílus találat esetén akkor is beíródik, ha a mező nem üres.

## Adatvédelem

Minden szolgáltató külön kapcsolható. Ami ki van kapcsolva, ahhoz nem megy hívás.

| Szolgáltató | Alapból | Mi megy ki |
| --- | --- | --- |
| Shazam | be | hangminta, nem a fájl útvonala |
| Beatport | be | felhasználónév és jelszó a belépéshez, utána előadó és cím, vagy ISRC, vagy a beírt track ID |
| Spotify | be, ha van kulcs | Client ID és Client Secret a belépéshez, utána előadó és cím |
| Deezer | be | előadó és cím, vagy ISRC |
| Apple | be | előadó és cím |
| MusicBrainz | be | előadó és cím, vagy ISRC |
| Discogs | be | előadó és cím |
| Bing | ki | előadó és cím, csak ha a webes keresést bekapcsolod |
| Grok, Gemini | ki, amíg nincs kulcs | fájlnév, bent lévő tag, a jelölt adatai és a hossz. A hangfájl nem |

A program nem küldi el a fájl útvonalát. A Beatport jelszó csak a Beatportnak megy. A Spotify titok csak a Spotify token végpontnak. Az AI kulcs csak a saját szolgáltatójának. A többi katalógusnak nem kell kulcs.

## Pontosabb találat

A program a fájl hosszát hasonlítja a katalógus hosszához. Ha a kettő 6 másodpercnél és a hosszabbik 4%-ánál is jobban eltér, a találatot eldobja. Ha a fájlban már van borító, és a találat borítója szemmel láthatóan más, azt a találatot is kihagyja.

A Shazam-találatot a fájlnévvel és a bent lévő taggel is összeveti. A `Matt Guy - Chorale.mp3` nem lehet `bbno$ - check`. Ha a kettő eltér, a hangmintát kihagyja, és a fájlnév alapján keres.

Ha a találat bizonytalan, és megvan mind a két kulcs, a Grok és a Gemini ugyanazt a jelöltet látja. Csak akkor lesz zöld, ha mindkettő ugyanazt a felvételt fogadja el. Egy elutasításnál a fájl nem változik (`! AI nem`). Egy kulcsnál a sor sárga marad.

Az Open Key (`1m`, `1d`) és a zenei nevek (`Amin`, `F# minor`) Camelot kódra váltanak, például `8A`. A Traxsource nincs bekötve. Automatikus hot cue és helyi BPM-elemzés sincs. A kézzel beírt Beatport linket akkor is használja, ha a hossz kicsit eltér.

A frissítés csak akkor indul el, ha a GitHub kiadás leírásában lévő `SHA256:` sor egyezik a letöltött `MusicIDTagger-Setup.exe` fájllal.

## Amit ebből raktam össze

| Feladat | Forrás |
| --- | --- |
| Hangfelismerés | [shazamio/ShazamIO](https://github.com/shazamio/ShazamIO) 0.9, Windows-on ffmpeg nélkül |
| Beatport BPM / hangnem / stílus | beets-beatport4 és kemo beatport-api-client |
| Spotify album / év / ISRC | hivatalos Spotify Web API, client credentials |
| Deezer, Apple, MusicBrainz | nyilvános kereső, kulcs nélkül |
| Discogs | nyilvános kereső, kulcs nélkül. Kiadó, katalógusszám, hossz |
| Tag írás | mutagen, Rekordbox-barát TKEY / TBPM / TPUB |
| Telepítő | PyInstaller onedir + Inno Setup 6. A natív Shazam könyvtár onefile exe-ben eltörik |
| Ha minden bolt kell | [OneTagger](https://onetagger.github.io/) már tud Traxsource-t, Junót és Beatsource-t is |

## Saját fordítás

64 bites Python 3.12 kell. A `Python312-32` mappa 32 bites, arra a Shazam csomag nem települ.

```powershell
powershell -ExecutionPolicy Bypass -File .\build\build.ps1
```

A kész telepítő: `installer\Output\MusicIDTagger-Setup.exe`.
A GitHub Actions a `main` ágon lefordítja. Kiadás csak `v*` címkére készül, a leírásban a telepítő SHA256 sorával.
