from __future__ import annotations

import re
from typing import Any, Callable
from urllib.parse import parse_qs, urlparse

from music_id_tagger.match import (
    beatport_genre,
    best_track,
    camelot_or_name,
    clean,
    musical_key_name,
    year_from,
)

API = "https://api.beatport.com"
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)
REDIRECT_URI = "https://api.beatport.com/v4/auth/o/post-message/"


class BeatportError(Exception):
    pass


def _name(value: Any) -> str | None:
    if isinstance(value, dict):
        text = clean(value.get("name"))
        return text or None
    if isinstance(value, list) and value:
        return _name(value[0])
    text = clean(value)
    return text or None


_TRACK_ID = re.compile(r"beatport\.com/(?:[a-z]{2}/)?track/(?:[^/?#]+/)?(\d+)", re.I)
_BARE_ID = re.compile(r"^\d{4,12}$")


def parse_beatport_id(value) -> str | None:
    """The number at the end of a Beatport track link, or a bare catalog id."""
    text = clean(value)
    if not text:
        return None
    match = _TRACK_ID.search(text.replace("\\", "/"))
    if match:
        return match.group(1)
    if _BARE_ID.match(text):
        return text
    return None


def beatport_track_url(track: dict) -> str | None:
    slug = clean(track.get("slug"))
    ident = track.get("id")
    if slug and ident not in (None, ""):
        return f"https://www.beatport.com/track/{slug}/{ident}"
    direct = clean(track.get("url"))
    if direct.startswith("https://www.beatport.com/track/"):
        return direct
    return None


def _cover_url(track: dict) -> str | None:
    for source in (track.get("image"), (track.get("release") or {}).get("image") if isinstance(track.get("release"), dict) else None):
        if isinstance(source, str) and source.startswith("http"):
            return source
        if not isinstance(source, dict):
            continue
        dynamic = clean(source.get("dynamic_uri") or source.get("dynamic_url"))
        if dynamic:
            return dynamic.replace("{w}", "500").replace("{h}", "500")
        uri = clean(source.get("uri") or source.get("url"))
        if uri.startswith("http"):
            return uri
    return None


def _duration(track: dict):
    from music_id_tagger.reconcile import duration_seconds

    raw_ms = track.get("length_ms")
    if raw_ms not in (None, "", 0):
        try:
            return duration_seconds(float(raw_ms) / 1000.0)
        except (TypeError, ValueError):
            return None
    return duration_seconds(track.get("length"))


def normalize_track(track: dict) -> dict[str, Any]:
    artists = ", ".join(
        clean(item.get("name"))
        for item in (track.get("artists") or [])
        if isinstance(item, dict) and clean(item.get("name"))
    )
    release = track.get("release") if isinstance(track.get("release"), dict) else {}
    label = release.get("label") if isinstance(release.get("label"), dict) else track.get("label")
    key = track.get("key")
    bpm = track.get("bpm")
    bpm_value = None
    if bpm not in (None, ""):
        try:
            bpm_value = int(round(float(bpm)))
        except (TypeError, ValueError):
            bpm_value = None
    genre = beatport_genre(_name(track.get("genre")), _name(track.get("sub_genre") or track.get("subgenre")))
    catalog = clean(
        track.get("catalog_number")
        or release.get("catalog_number")
        or release.get("catalog_nr")
    ) or None
    return {
        "title": clean(track.get("name") or track.get("title")) or None,
        "artist": artists or None,
        "album": clean(release.get("name")) or None,
        "year": year_from(
            track.get("publish_date")
            or track.get("new_release_date")
            or release.get("publish_date")
            or release.get("new_release_date")
        ),
        "genre": genre,
        "bpm": bpm_value,
        "duration": _duration(track),
        "key": camelot_or_name(key),
        "key_name": musical_key_name(key),
        "label": _name(label),
        "mix": clean(track.get("mix_name")) or None,
        "beatport_id": track.get("id"),
        "isrc": clean(track.get("isrc")) or None,
        "catalog": catalog,
        "cover_url": _cover_url(track),
        "source_url": beatport_track_url(track),
        "source": "beatport",
    }


class BeatportClient:
    """Beatport v4: docs client_id, session login, authorization code, catalog search.

    Same path as kemo/beatport-api-client and beets-beatport4. Password stays in memory.
    """

    def __init__(self) -> None:
        import requests

        self.session = requests.Session()
        self.session.headers["User-Agent"] = UA
        self.client_id: str | None = None
        self.access_token: str | None = None
        self.refresh_token: str | None = None

    def scrape_client_id(self) -> str:
        if self.client_id:
            return self.client_id
        page = self.session.get(f"{API}/v4/docs/", timeout=20)
        page.raise_for_status()
        paths = re.findall(r"/static/btprt/[^\"']+\.js", page.text)
        seen: set[str] = set()
        for path in paths:
            if path in seen:
                continue
            seen.add(path)
            script = self.session.get(API + path, timeout=20)
            if script.status_code != 200:
                continue
            match = re.search(r"API_CLIENT_ID:\s*['\"]([^'\"]+)['\"]", script.text)
            if match:
                self.client_id = match.group(1)
                return self.client_id
        raise BeatportError("A Beatport docs oldalról nem jött ki client_id.")

    def login(self, username: str, password: str) -> None:
        client_id = self.scrape_client_id()
        login = self.session.post(
            f"{API}/v4/auth/login/",
            json={"username": username, "password": password},
            headers={"Accept": "application/json"},
            timeout=25,
        )
        if login.status_code != 200:
            raise BeatportError(f"Beatport belépés elutasítva ({login.status_code}).")

        auth = self.session.get(
            f"{API}/v4/auth/o/authorize/",
            params={
                "response_type": "code",
                "client_id": client_id,
                "redirect_uri": REDIRECT_URI,
            },
            allow_redirects=False,
            timeout=25,
        )
        location = auth.headers.get("Location") or ""
        parsed = urlparse(location)
        code = (parse_qs(parsed.query).get("code") or parse_qs(parsed.fragment).get("code") or [None])[0]
        if not code:
            raise BeatportError("A Beatport nem adott belépési kódot.")

        token = self.session.post(
            f"{API}/v4/auth/o/token/",
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": REDIRECT_URI,
                "client_id": client_id,
                "code_verifier": "",
            },
            timeout=25,
        )
        if token.status_code != 200:
            raise BeatportError(f"Beatport token csere sikertelen ({token.status_code}).")
        body = token.json()
        self.access_token = body.get("access_token")
        self.refresh_token = body.get("refresh_token")
        if not self.access_token:
            raise BeatportError("A Beatport válasza nem tartalmaz access tokent.")

    def _refresh(self) -> bool:
        if not self.refresh_token or not self.client_id:
            return False
        token = self.session.post(
            f"{API}/v4/auth/o/token/",
            data={
                "grant_type": "refresh_token",
                "refresh_token": self.refresh_token,
                "client_id": self.client_id,
            },
            timeout=25,
        )
        if token.status_code != 200:
            return False
        body = token.json()
        self.access_token = body.get("access_token") or self.access_token
        if body.get("refresh_token"):
            self.refresh_token = body["refresh_token"]
        return bool(body.get("access_token"))

    def search(self, artist: str, title: str, log: Callable[[str, str], None] | None = None, file_duration=None) -> dict[str, Any] | None:
        if not self.access_token or not clean(artist) or not clean(title):
            return None
        query = f"{clean(artist)} {clean(title)}"
        response = self._get_search(query)
        if response is None:
            return None
        if response.status_code == 401 and self._refresh():
            response = self._get_search(query)
        if response is None or response.status_code != 200:
            code = response.status_code if response is not None else 0
            if log:
                log("err", f"Beatport keresés hiba ({code}).")
            return None
        data = response.json()
        tracks = data.get("tracks") or data.get("results") or []
        if isinstance(tracks, dict):
            tracks = tracks.get("data") or tracks.get("results") or []
        from music_id_tagger.reconcile import prefer_duration

        tracks, dropped = prefer_duration(tracks, file_duration)
        if not tracks and dropped:
            if log:
                log("muted", f"Beatport: a találatok hossza nem egyezik a fájllal — {query}")
            return None
        winner, score = best_track(tracks, artist, title)
        if not winner:
            if log:
                log("muted", f"Beatport: nincs elég biztos találat erre: {query}")
            return None
        meta = normalize_track(winner)
        meta["match_score"] = score
        ident = parse_beatport_id(meta.get("source_url")) or parse_beatport_id(meta.get("beatport_id"))
        if ident:
            meta["beatport_id"] = ident
        return meta

    def by_id(self, track_id, log: Callable[[str, str], None] | None = None) -> dict[str, Any] | None:
        ident = parse_beatport_id(track_id)
        if not self.access_token or not ident:
            return None
        response = self._get_track(ident)
        if response is not None and response.status_code == 401 and self._refresh():
            response = self._get_track(ident)
        if response is None or response.status_code != 200:
            code = response.status_code if response is not None else 0
            if log:
                log("err", f"Beatport ID {ident} nem tölthető ({code}).")
            return None
        body = response.json()
        track = body if isinstance(body, dict) and (body.get("id") or body.get("name")) else None
        if track is None and isinstance(body, dict):
            nested = body.get("track") or body.get("data") or body.get("results")
            if isinstance(nested, list):
                nested = nested[0] if nested else None
            if isinstance(nested, dict):
                track = nested
        if not isinstance(track, dict):
            if log:
                log("err", f"Beatport ID {ident}: üres válasz.")
            return None
        meta = normalize_track(track)
        meta["beatport_id"] = ident
        meta["match_score"] = 100
        meta["source_url"] = meta.get("source_url") or f"https://www.beatport.com/track/{ident}"
        return meta

    def by_isrc(self, isrc: str, log: Callable[[str, str], None] | None = None) -> dict[str, Any] | None:
        code = re.sub(r"[^A-Za-z0-9]", "", clean(isrc)).upper()
        if not self.access_token or len(code) < 12:
            return None
        response = self._get_path(f"/v4/catalog/tracks/store/{code}/")
        if response is not None and response.status_code == 401 and self._refresh():
            response = self._get_path(f"/v4/catalog/tracks/store/{code}/")
        if response is not None and response.status_code == 200:
            meta = self._meta_from_body(response.json(), log)
            if meta:
                meta["match_score"] = 100
                return meta
        response = self._get_search(code)
        if response is None or response.status_code != 200:
            return None
        data = response.json()
        tracks = data.get("tracks") or data.get("results") or []
        if isinstance(tracks, dict):
            tracks = tracks.get("data") or tracks.get("results") or []
        for track in tracks:
            if not isinstance(track, dict):
                continue
            got = re.sub(r"[^A-Za-z0-9]", "", clean(track.get("isrc"))).upper()
            if got and got == code:
                meta = normalize_track(track)
                meta["match_score"] = 100
                ident = parse_beatport_id(meta.get("source_url")) or parse_beatport_id(meta.get("beatport_id"))
                if ident:
                    meta["beatport_id"] = ident
                return meta
        return None

    def _meta_from_body(self, body, log):
        track = body if isinstance(body, dict) and (body.get("name") or body.get("artists")) else None
        if track is None and isinstance(body, dict):
            ident = parse_beatport_id(body.get("url") or body.get("id"))
            if ident:
                return self.by_id(ident, log)
        if not isinstance(track, dict):
            return None
        meta = normalize_track(track)
        ident = parse_beatport_id(meta.get("source_url")) or parse_beatport_id(meta.get("beatport_id"))
        if ident:
            meta["beatport_id"] = ident
        return meta

    def _get_path(self, path: str):
        from music_id_tagger.net import session_get

        return session_get(
            self.session,
            f"{API}{path}",
            headers={"Authorization": f"Bearer {self.access_token}"},
        )

    def _get_track(self, track_id: str):
        from music_id_tagger.net import session_get

        return session_get(
            self.session,
            f"{API}/v4/catalog/tracks/{track_id}/",
            headers={"Authorization": f"Bearer {self.access_token}"},
        )

    def _get_search(self, query: str):
        from music_id_tagger.net import session_get

        return session_get(
            self.session,
            f"{API}/v4/catalog/search/",
            params={"q": query, "type": "tracks", "per_page": 10},
            headers={"Authorization": f"Bearer {self.access_token}"},
        )
