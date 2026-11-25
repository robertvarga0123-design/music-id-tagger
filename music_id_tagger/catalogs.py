"""Keyless catalogs: Deezer, Apple Music (iTunes Search), MusicBrainz and Discogs.

Deezer's full track carries a measured BPM, a duration and an ISRC. Apple fills album and year.
MusicBrainz resolves an ISRC to a recording. Discogs adds label, catalog number and the
per-track length of a release. None of them replaces a Beatport genre.
Calls are skipped by the engine when the file already has the fields they would fill.
"""

from __future__ import annotations

import re
import threading
import time
from typing import Any, Callable

from music_id_tagger.match import clean, genre_is_generic, score_track, year_from
from music_id_tagger.net import USER_AGENT, session_get
from music_id_tagger.reconcile import duration_seconds, durations_compatible

Log = Callable[[str, str], None] | None

_lock = threading.Lock()
_last = {"deezer": 0.0, "apple": 0.0, "musicbrainz": 0.0, "discogs": 0.0}
_GAP = {"deezer": 0.25, "apple": 3.0, "musicbrainz": 1.1, "discogs": 2.5}
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


def _best(items: list, artist: str, title: str, to_meta, file_duration=None) -> dict | None:
    winner: dict | None = None
    best = -1
    for item in items:
        if not isinstance(item, dict):
            continue
        meta = to_meta(item)
        if not meta or not clean(meta.get("title")) or not clean(meta.get("artist")):
            continue
        if file_duration is not None and meta.get("duration") is not None:
            if durations_compatible(file_duration, meta.get("duration")) is False:
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
        "duration": duration_seconds(track.get("duration")),
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
    millis = item.get("trackTimeMillis")
    duration = None
    if millis not in (None, "", 0):
        try:
            duration = duration_seconds(float(millis) / 1000.0)
        except (TypeError, ValueError):
            duration = None
    genre = clean(item.get("primaryGenreName"))
    if genre_is_generic(genre):
        genre = ""
    meta = {
        "title": title,
        "artist": artist,
        "album": clean(item.get("collectionName")) or None,
        "year": year_from(item.get("releaseDate")),
        "duration": duration,
        "cover_url": art or None,
        "source_url": url if url.startswith("https://music.apple.com/") or url.startswith("https://itunes.apple.com/") else None,
        "source": "apple",
    }
    if genre:
        meta["genre"] = genre
    return meta


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
    length = recording.get("length")
    duration = None
    if length not in (None, "", 0):
        try:
            duration = duration_seconds(float(length) / 1000.0)
        except (TypeError, ValueError):
            duration = None
    meta = {
        "title": title or None,
        "artist": ", ".join(names) or None,
        "album": album or None,
        "year": year_from(date),
        "duration": duration,
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


def deezer_search(artist: str, title: str, log: Log = None, file_duration=None) -> dict | None:
    if not clean(artist) or not clean(title):
        return None
    body = _json(
        "https://api.deezer.com/search/track",
        {"q": f"{clean(artist)} {clean(title)}", "limit": 8},
        "deezer",
    )
    items = (body or {}).get("data") if isinstance(body, dict) else None
    chosen = _best(items or [], artist, title, meta_from_deezer, file_duration)
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


def itunes_search(artist: str, title: str, log: Log = None, file_duration=None) -> dict | None:
    if not clean(artist) or not clean(title):
        return None
    body = _json(
        "https://itunes.apple.com/search",
        {"term": f"{clean(artist)} {clean(title)}", "entity": "song", "media": "music", "limit": 8, "country": "us"},
        "apple",
    )
    chosen = _best((body or {}).get("results") or [], artist, title, meta_from_itunes, file_duration)
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


def musicbrainz_search(artist: str, title: str, log: Log = None, file_duration=None) -> dict | None:
    if not clean(artist) or not clean(title):
        return None
    query = f'recording:"{clean(title).replace(chr(34), "")}" AND artist:"{clean(artist).replace(chr(34), "")}"'
    body = _json(
        "https://musicbrainz.org/ws/2/recording/",
        {"query": query, "fmt": "json", "limit": 5},
        "musicbrainz",
    )
    recordings = (body or {}).get("recordings") if isinstance(body, dict) else None
    chosen = _best(recordings or [], artist, title, meta_from_musicbrainz, file_duration)
    if not chosen and log:
        log("muted", f"MusicBrainz: nincs elég biztos találat — {clean(artist)} - {clean(title)}")
    return chosen


_DISAMBIG = re.compile(r"\s*\(\d+\)$")
_TRACK_MIX = re.compile(r"^(?P<title>.+?)\s*\((?P<mix>[^)]*)\)\s*$")


def _discogs_name(value: Any) -> str:
    return _DISAMBIG.sub("", clean(value))


def _split_track(raw: Any) -> tuple[str, str]:
    text = clean(raw)
    match = _TRACK_MIX.match(text)
    if not match:
        return text, ""
    return clean(match.group("title")), clean(match.group("mix"))


def meta_from_discogs(release: dict, artist: str, title: str, file_duration=None) -> dict[str, Any] | None:
    """One Discogs release, narrowed to the track whose length matches the file."""
    if not isinstance(release, dict):
        return None
    names = [_discogs_name(item.get("name")) for item in (release.get("artists") or []) if isinstance(item, dict)]
    who = ", ".join(name for name in names if name) or clean(artist)
    best_title = ""
    best_mix = ""
    best_seconds = None
    best_score = -1
    comparable = False
    for track in release.get("tracklist") or []:
        if not isinstance(track, dict):
            continue
        track_title, mix = _split_track(track.get("title"))
        seconds = duration_seconds(track.get("duration"))
        if seconds is not None:
            comparable = True
        if file_duration is not None and seconds is not None and durations_compatible(file_duration, seconds) is False:
            continue
        score = score_track(_candidate(track_title, who, mix), artist, title)
        if score > best_score:
            best_score = score
            best_title = track_title
            best_mix = mix
            best_seconds = seconds
    if best_score < 12 or not best_title:
        return None
    if file_duration is not None and comparable and best_seconds is None:
        return None
    labels = [item for item in (release.get("labels") or []) if isinstance(item, dict)]
    label = _discogs_name(labels[0].get("name")) if labels else ""
    catno = clean(labels[0].get("catno")) if labels else ""
    if catno.lower() in {"none", "n/a", "na"}:
        catno = ""
    cover = ""
    for image in release.get("images") or []:
        if not isinstance(image, dict):
            continue
        uri = clean(image.get("uri"))
        if uri.startswith("https://"):
            cover = uri
            break
    ident = release.get("id")
    return {
        "title": best_title,
        "artist": who or None,
        "mix": best_mix or None,
        "album": clean(release.get("title")) or None,
        "year": year_from(release.get("year") or release.get("released")),
        "label": label or None,
        "catalog": catno or None,
        "duration": best_seconds,
        "cover_url": cover or None,
        "source_url": f"https://www.discogs.com/release/{ident}" if ident else None,
        "source": "discogs",
        "match_score": best_score,
    }


def discogs_search(artist: str, title: str, log: Log = None, file_duration=None) -> dict | None:
    if not clean(artist) or not clean(title):
        return None
    body = _json(
        "https://api.discogs.com/database/search",
        {"artist": clean(artist), "track": clean(title), "type": "release", "per_page": 5},
        "discogs",
    )
    results = (body or {}).get("results") if isinstance(body, dict) else None
    if not results:
        if log:
            log("muted", f"Discogs: nincs találat — {clean(artist)} - {clean(title)}")
        return None
    checked = 0
    for item in results:
        if checked >= 3:
            break
        if not isinstance(item, dict) or not item.get("id"):
            continue
        checked += 1
        release = _json(f"https://api.discogs.com/releases/{item['id']}", None, "discogs")
        meta = meta_from_discogs(release or {}, artist, title, file_duration)
        if meta:
            return meta
    if log:
        log("muted", f"Discogs: a hossz vagy a cím nem egyezik — {clean(artist)} - {clean(title)}")
    return None

