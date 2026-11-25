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
3. Adj hozzá mappákat, írd be a Beatport felhasználót és jelszót, majd nyomd meg a Keresést.
4. Az Eredmények fülön nézd át a tervet. Az Alkalmaz gomb írja be a kijelölt vagy a biztos sorokat. A Visszavonás vissza tudja tenni.

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

## Újdonságok az 1.5-ben

A keresés és az írás külön lépés. A **Keresés** csak tervet készít. A fájl akkor változik, ha az Eredmények fülön az **Alkalmaz** gombot megnyomod. A visszavonás a taget és az átnevezést is vissza tudja tenni.

Négy fül:

1. **Könyvtár.** Ide húzod a mappát, a zenét vagy a Rekordbox XML-t. Ha üres, a „Húzd ide a mappát” felirat látszik. Itt van az Újrakeresés, a „csak a hiányzó mezőket” és a „taggel először” kapcsoló. A Keresés gomb lent mindig látszik.
2. **Eredmények.** Soronként a régi és az új érték, a forrás és a megbízhatóság. Jobb oldalt mezőnkénti pipa és borító. Szűrő: mind, bizonytalan, nincs találat, hiba, változás van. Dupla kattintás a bizonytalan soron: a Beatport első három találata, vagy kézi link / ID, vagy kihagyás. Gombok: kijelöltek alkalmazása, összes biztos alkalmazása, visszavonás, CSV, duplikátumok.
3. **Beállítások.** Szolgáltatók és kulcsok, írandó mezők, hangnem formátuma (Camelot, Open Key vagy hagyományos név), műfaj-leképezés, fájlnév-sablon, cache törlése, frissítés.
4. **Napló.** Info vagy hiba, másolás, mentés fájlba.

A munkamenet: Keresés → átnézed a tervet → Alkalmaz → ha nem jó, Visszavonás.

A változatlan fájl a `cache.db` miatt nem kérdez újra hálózatot. Az Újrakeresés pipa ezt felülírja. A megszakított futás a kész sorokat kihagyja. A „csak hiányzó” mód a már kitöltött fájlt hálózat nélkül hagyja. A „taggel először” Beatportot kérdez, és Shazamot csak akkor, ha a Beatport nem találta.

A hangnem mind a 24 Camelot kódon oda-vissza átváltható Open Key-re (`8A` = `1m`) és hagyományos névre (`8A` = `Am`). A műfaj-tábla csak íráskor cserél, például `Techno (Peak Time / Driving)` → `Peak Techno`.

A CSV a fájlt, az állapotot, a régi és az új értéket, a forrást és a megbízhatóságot írja. A duplikátumlista közös ISRC vagy Beatport ID szerint csoportosít, és jelzi, ha a hossz eltér. Nem töröl.

A fájlnév-sablon alapból ki van kapcsolva. Ha beírod, a tiltott karakterek lekerülnek, ütközésnél `név (2).mp3` lesz, és a Rekordbox XML `Location` mezője követi az új nevet. Az átnevezés visszavonható.

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
