from __future__ import annotations

import base64
import time
from typing import Any, Callable

from music_id_tagger.match import best_track, clean, year_from

TOKEN_URL = "https://accounts.spotify.com/api/token"
API = "https://api.spotify.com/v1"

# Pitch class 0 = C … 11 = B. Spotify mode 1 = major, 0 = minor.
_CAMELOT_MAJOR = ["8B", "3B", "10B", "5B", "12B", "7B", "2B", "9B", "4B", "11B", "6B", "1B"]
_CAMELOT_MINOR = ["5A", "12A", "7A", "2A", "9A", "4A", "11A", "6A", "1A", "8A", "3A", "10A"]
_NOTE = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]


class SpotifyError(Exception):
    pass


def spotify_key(pitch: Any, mode: Any) -> tuple[str | None, str | None]:
    try:
        pitch_i = int(pitch)
        mode_i = int(mode)
    except (TypeError, ValueError):
        return None, None
    if pitch_i < 0 or pitch_i > 11:
        return None, None
    if mode_i == 1:
        return _CAMELOT_MAJOR[pitch_i], f"{_NOTE[pitch_i]} Major"
    if mode_i == 0:
        return _CAMELOT_MINOR[pitch_i], f"{_NOTE[pitch_i]}m"
    return None, None


def normalize_track(track: dict, features: dict | None = None) -> dict[str, Any]:
    artists = ", ".join(
        clean(item.get("name"))
        for item in (track.get("artists") or [])
        if isinstance(item, dict) and clean(item.get("name"))
    )
    album = track.get("album") if isinstance(track.get("album"), dict) else {}
    images = [item for item in (album.get("images") or []) if isinstance(item, dict) and item.get("url")]
    images.sort(key=lambda item: int(item.get("width") or 0), reverse=True)
    external = track.get("external_ids") if isinstance(track.get("external_ids"), dict) else {}
    meta: dict[str, Any] = {
        "title": clean(track.get("name")) or None,
        "artist": artists or None,
        "album": clean(album.get("name")) or None,
        "year": year_from(album.get("release_date")),
        "isrc": clean(external.get("isrc")) or None,
        "cover_url": images[0]["url"] if images else None,
        "spotify_id": clean(track.get("id")) or None,
        "source": "spotify",
    }
    if features:
        tempo = features.get("tempo")
        if tempo not in (None, ""):
            try:
                meta["bpm"] = int(round(float(tempo)))
            except (TypeError, ValueError):
                pass
        camelot, name = spotify_key(features.get("key"), features.get("mode"))
        if camelot:
            meta["key"] = camelot
            meta["key_name"] = name
    return meta


class SpotifyClient:
    """Hivatalos Spotify Web API, client credentials.

    A katalóguskeresés albumot, évet, ISRC-t és borítót ad.
    Az audio-features (BPM, hangnem) 2024. november 27. óta új appoknak 403.
    Ha mégis válaszol, BPM-et és Camelotot tölt. Különben ezek a Beatporttól jönnek.
    A client secret nincs elmentve.
    """

    def __init__(self) -> None:
        import requests

        self.session = requests.Session()
        self.session.headers["User-Agent"] = "MusicIDTagger/1.0"
        self.client_id = ""
        self.client_secret = ""
        self.access_token: str | None = None
        self.expires_at = 0.0
        self.features_disabled = False

    def login(self, client_id: str, client_secret: str) -> None:
        self.client_id = client_id.strip()
        self.client_secret = client_secret.strip()
        if not self.client_id or not self.client_secret:
            raise SpotifyError("Hiányzik a Spotify Client ID vagy a Client Secret.")
        self._token()

    def _token(self) -> None:
        raw = f"{self.client_id}:{self.client_secret}".encode()
        basic = base64.b64encode(raw).decode("ascii")
        response = self.session.post(
            TOKEN_URL,
            data={"grant_type": "client_credentials"},
            headers={"Authorization": f"Basic {basic}"},
            timeout=20,
        )
        if response.status_code != 200:
            raise SpotifyError(f"Spotify belépés elutasítva ({response.status_code}).")
        body = response.json()
        token = body.get("access_token")
        if not token:
            raise SpotifyError("A Spotify nem adott tokent.")
        self.access_token = token
        self.expires_at = time.monotonic() + max(30, int(body.get("expires_in") or 3600) - 30)

    def _headers(self) -> dict[str, str]:
        if not self.access_token or time.monotonic() >= self.expires_at:
            self._token()
        return {"Authorization": f"Bearer {self.access_token}"}

    def search(self, artist: str, title: str, log: Callable[[str, str], None] | None = None) -> dict[str, Any] | None:
        if not clean(artist) or not clean(title):
            return None
        query = f'artist:"{clean(artist).replace(chr(34), "")}" track:"{clean(title).replace(chr(34), "")}"'
        response = self._get("/search", {"q": query, "type": "track", "limit": 10})
        if response is None:
            return None
        if response.status_code == 401:
            self.access_token = None
            response = self._get("/search", {"q": query, "type": "track", "limit": 10})
        if response is None or response.status_code != 200:
            code = response.status_code if response is not None else 0
            if log:
                log("err", f"Spotify keresés hiba ({code}).")
            return None
        items = ((response.json().get("tracks") or {}).get("items")) or []
        winner, score = best_track(items, artist, title)
        if not winner:
            if log:
                log("muted", f"Spotify: nincs elég biztos találat erre: {clean(artist)} - {clean(title)}")
            return None
        full = self._track(str(winner.get("id") or ""))
        track = full or winner
        features = self._features(str(track.get("id") or winner.get("id") or ""), log)
        meta = normalize_track(track, features)
        meta["match_score"] = score
        return meta

    def _track(self, track_id: str) -> dict | None:
        if not track_id:
            return None
        response = self._get(f"/tracks/{track_id}", {})
        if response is None or response.status_code != 200:
            return None
        body = response.json()
        return body if isinstance(body, dict) else None

    def _features(self, track_id: str, log: Callable[[str, str], None] | None) -> dict | None:
        if self.features_disabled or not track_id:
            return None
        response = self._get(f"/audio-features/{track_id}", {})
        if response is None:
            return None
        if response.status_code == 403:
            self.features_disabled = True
            if log:
                log("muted", "A Spotify nem ad BPM-et és hangnemet. Ezek a Beatporttól jönnek.")
            return None
        if response.status_code != 200:
            return None
        body = response.json()
        return body if isinstance(body, dict) else None

    def _get(self, path: str, params: dict):
        try:
            return self.session.get(API + path, params=params or None, headers=self._headers(), timeout=20)
        except Exception:
            return None
