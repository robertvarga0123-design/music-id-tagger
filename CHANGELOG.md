# Változások

## 1.5.1

- A frissítés gomb többé nem a Windows „nem találja: \\” ablakát nyitja. A telepítő egy rövid várakozás után indul, parancssor nélkül.

## 1.5.0

- A keresés csak tervet készít. Az írás külön Alkalmaz lépés, visszavonható.
- SQLite cache: a változatlan fájl nem kérdez újra hálózatot. Újrakeresés pipával igen. A megszakított futás a kész sorokat kihagyja.
- Mezőnkénti pipák, csak a hiányzó mezők, taggel először (Beatport, aztán Shazam).
- Bizonytalan sornál a Beatport első három találata, vagy kézi link.
- Hangnem: Camelot, Open Key vagy hagyományos név. Mind a 24 kulcs oda-vissza.
- Szerkeszthető műfaj-leképezés, CSV, duplikátumlista. A lista nem töröl.
- Opcionális fájlnév-sablon, ütközésnél sorszám, Rekordbox Location frissítés, visszavonható átnevezés.
- Négy fül: Könyvtár, Eredmények, Beállítások, Napló. Állapotsáv, ETA, megállítás a folyamatban lévő fájl után.

## 1.4.1

- A telepítő SHA256 ellenőrzése. A frissítés csak a saját GitHub kiadás `MusicIDTagger-Setup.exe` fájlját fogadja el.
- A nem változó tizedes BPM nem íródik újra.
- Webes keresés alapból ki. Szolgáltatónkénti kapcsoló.
- Általános műfaj (Dance, Pop, Electronic, Electronica, Music) nem ír felül DJ-stílust.
- A jelszó parancssorban a környezeti változóból vagy csendes bekérésből jön. Üres titokmező nem törli a mentettet.
