"""Keyless catalogs: Deezer, Apple Music (iTunes Search) and MusicBrainz.

Deezer's full track carries a measured BPM and an ISRC. Apple fills album and year.
MusicBrainz resolves an ISRC to a recording. None of them replaces a Beatport genre.
Calls are skipped by the engine when the file already has the fields they would fill.
"""

from __future__ import annotations

import threading
import time
from typing import Any, Callable

from music_id_tagger.match import clean, score_track, year_from
from music_id_tagger.net import USER_AGENT, session_get

Log = Callable[[str, str], None] | None

_lock = threading.Lock()
_last = {"deezer": 0.0, "apple": 0.0, "musicbrainz": 0.0}
_GAP = {"deezer": 0.25, "apple": 3.0, "musicbrainz": 1.1}
_session = None


def _http():
    global _session
    if _session is None:
        import requests

        _session = requests.Session()
        _session.headers["User-Agent"] = USER_AGENT
        _session.headers["Accept"] = "application/json"
    return _session


def _wait(name: str) -> None:
    with _lock:
        delay = _last[name] + _GAP[name] - time.monotonic()
        if delay > 0:
            time.sleep(delay)
        _last[name] = time.monotonic()


def _json(url: str, params: dict | None, bucket: str, attempts: int = 3) -> dict | None:
    _wait(bucket)
    response = session_get(_http(), url, params=params, attempts=attempts, timeout=20)
    if response is None or response.status_code != 200:
        return None
    try:
        body = response.json()
    except Exception:
        return None
    return body if isinstance(body, dict) else None


def _isrc(value: Any) -> str:
    return "".join(ch for ch in clean(value).upper() if ch.isalnum())


def _candidate(title: str, artist: str, mix: str = "") -> dict:
    return {"name": title, "mix_name": mix, "artists": [{"name": artist}]}


def _best(items: list, artist: str, title: str, to_meta) -> dict | None:
    winner: dict | None = None
    best = -1
    for item in items:
        if not isinstance(item, dict):
            continue
        meta = to_meta(item)
        if not meta or not clean(meta.get("title")) or not clean(meta.get("artist")):
            continue
        score = score_track(
            _candidate(clean(meta.get("title")), clean(meta.get("artist")), clean(meta.get("mix"))),
            artist,
            title,
        )
        if score > best:
            best = score
            winner = meta
    if winner is None or best < 12:
        return None
    winner["match_score"] = best
    return winner


def meta_from_deezer(track: dict) -> dict[str, Any] | None:
    if not isinstance(track, dict) or track.get("error"):
        return None
    title = clean(track.get("title_short") or track.get("title"))
    artist = track.get("artist") if isinstance(track.get("artist"), dict) else {}
    who = clean(artist.get("name"))
    if not title and not who:
        return None
    album = track.get("album") if isinstance(track.get("album"), dict) else {}
    bpm = track.get("bpm")
    bpm_value = None
    if bpm not in (None, "", 0, 0.0):
        try:
            number = float(bpm)
        except (TypeError, ValueError):
            number = 0.0
        if 0 < number <= 400:
            bpm_value = number
    link = clean(track.get("link"))
    return {
        "title": title or None,
        "artist": who or None,
        "mix": clean(track.get("title_version")) or None,
        "album": clean(album.get("title")) or None,
        "year": year_from(track.get("release_date")),
        "isrc": _isrc(track.get("isrc")) or None,
        "bpm": bpm_value,
        "cover_url": clean(album.get("cover_xl") or album.get("cover_big") or album.get("cover_medium")) or None,
        "source_url": link if link.startswith("https://www.deezer.com/") else None,
        "deezer_id": track.get("id"),
        "source": "deezer",
    }


def meta_from_itunes(item: dict) -> dict[str, Any] | None:
    if not isinstance(item, dict):
        return None
    title = clean(item.get("trackName"))
    artist = clean(item.get("artistName"))
    if not title or not artist:
        return None
    url = clean(item.get("trackViewUrl"))
    art = clean(item.get("artworkUrl100"))
    if art:
        art = art.replace("100x100bb", "600x600bb")
    return {
        "title": title,
        "artist": artist,
        "album": clean(item.get("collectionName")) or None,
        "year": year_from(item.get("releaseDate")),
        "cover_url": art or None,
        "source_url": url if url.startswith("https://music.apple.com/") or url.startswith("https://itunes.apple.com/") else None,
        "source": "apple",
    }


def meta_from_musicbrainz(recording: dict, *, exact: bool = False) -> dict[str, Any] | None:
    if not isinstance(recording, dict):
        return None
    title = clean(recording.get("title"))
    names: list[str] = []
    for credit in recording.get("artist-credit") or []:
        if not isinstance(credit, dict):
            continue
        artist = credit.get("artist") if isinstance(credit.get("artist"), dict) else {}
        name = clean(credit.get("name") or artist.get("name"))
        if name:
            names.append(name)
    releases = [item for item in (recording.get("releases") or []) if isinstance(item, dict)]
    album = ""
    date = ""
    for release in releases:
        if not album:
            album = clean(release.get("title"))
        if not date and release.get("date"):
            date = clean(release.get("date"))
        if album and date:
            break
    isrcs = recording.get("isrcs") if isinstance(recording.get("isrcs"), list) else []
    mbid = clean(recording.get("id"))
    if not title and not names and not mbid:
        return None
    meta = {
        "title": title or None,
        "artist": ", ".join(names) or None,
        "album": album or None,
        "year": year_from(date),
        "isrc": _isrc(isrcs[0]) if isrcs else None,
        "mbid": mbid or None,
        "source_url": f"https://musicbrainz.org/recording/{mbid}" if mbid else None,
        "source": "musicbrainz",
    }
    if exact:
        meta["match_score"] = 100
    elif recording.get("score") not in (None, ""):
        try:
            meta["match_score"] = float(recording["score"]) / 5.0
        except (TypeError, ValueError):
            pass
    return meta


def deezer_by_isrc(isrc: str, log: Log = None) -> dict | None:
    code = _isrc(isrc)
    if len(code) < 12:
        return None
    body = _json(f"https://api.deezer.com/track/isrc:{code}", None, "deezer")
    meta = meta_from_deezer(body or {})
    if not meta or not meta.get("title"):
        if log:
            log("muted", f"Deezer: nincs ISRC találat ({code}).")
        return None
    meta["match_score"] = 100
    meta["isrc"] = meta.get("isrc") or code
    return meta


def deezer_search(artist: str, title: str, log: Log = None) -> dict | None:
    if not clean(artist) or not clean(title):
        return None
    body = _json(
        "https://api.deezer.com/search/track",
        {"q": f"{clean(artist)} {clean(title)}", "limit": 8},
        "deezer",
    )
    items = (body or {}).get("data") if isinstance(body, dict) else None
    chosen = _best(items or [], artist, title, meta_from_deezer)
    if not chosen:
        if log:
            log("muted", f"Deezer: nincs elég biztos találat — {clean(artist)} - {clean(title)}")
        return None
    ident = chosen.get("deezer_id")
    if ident:
        full = _json(f"https://api.deezer.com/track/{ident}", None, "deezer")
        richer = meta_from_deezer(full or {})
        if richer and richer.get("title"):
            richer["match_score"] = chosen["match_score"]
            return richer
    return chosen


def itunes_search(artist: str, title: str, log: Log = None) -> dict | None:
    if not clean(artist) or not clean(title):
        return None
    body = _json(
        "https://itunes.apple.com/search",
        {"term": f"{clean(artist)} {clean(title)}", "entity": "song", "media": "music", "limit": 8, "country": "us"},
        "apple",
    )
    chosen = _best((body or {}).get("results") or [], artist, title, meta_from_itunes)
    if not chosen and log:
        log("muted", f"Apple: nincs elég biztos találat — {clean(artist)} - {clean(title)}")
    return chosen


def musicbrainz_by_isrc(isrc: str, log: Log = None) -> dict | None:
    code = _isrc(isrc)
    if len(code) < 12:
        return None
    body = _json(
        f"https://musicbrainz.org/ws/2/isrc/{code}",
        {"fmt": "json", "inc": "releases+artist-credits+isrcs"},
        "musicbrainz",
        attempts=3,
    )
    if not body:
        body = _json(f"https://musicbrainz.org/ws/2/isrc/{code}", {"fmt": "json"}, "musicbrainz")
    recordings = (body or {}).get("recordings") if isinstance(body, dict) else None
    if not recordings:
        if log:
            log("muted", f"MusicBrainz: nincs ISRC találat ({code}).")
        return None
    meta = meta_from_musicbrainz(recordings[0], exact=True)
    if meta:
        meta["isrc"] = meta.get("isrc") or code
    return meta


def musicbrainz_search(artist: str, title: str, log: Log = None) -> dict | None:
    if not clean(artist) or not clean(title):
        return None
    query = f'recording:"{clean(title).replace(chr(34), "")}" AND artist:"{clean(artist).replace(chr(34), "")}"'
    body = _json(
        "https://musicbrainz.org/ws/2/recording/",
        {"query": query, "fmt": "json", "limit": 5},
        "musicbrainz",
    )
    recordings = (body or {}).get("recordings") if isinstance(body, dict) else None
    chosen = _best(recordings or [], artist, title, meta_from_musicbrainz)
    if not chosen and log:
        log("muted", f"MusicBrainz: nincs elég biztos találat — {clean(artist)} - {clean(title)}")
    return chosen
