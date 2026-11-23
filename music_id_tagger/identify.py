from __future__ import annotations

from pathlib import Path
from typing import Any

from music_id_tagger.match import clean, year_from


def _dump(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, dict):
        return value
    if hasattr(value, "model_dump"):
        return value.model_dump()
    if hasattr(value, "dict"):
        return value.dict()
    return value


def _section_fields(track: dict) -> dict[str, str]:
    found: dict[str, str] = {}
    for section in track.get("sections") or []:
        section = _dump(section)
        if not isinstance(section, dict):
            continue
        rows = section.get("metadata") or []
        for row in rows:
            row = _dump(row)
            if not isinstance(row, dict):
                continue
            key = clean(row.get("title")).lower()
            text = clean(row.get("text"))
            if key and text and key not in found:
                found[key] = text
    return found


def _shazam_url(track: dict) -> str | None:
    share = track.get("share") if isinstance(track.get("share"), dict) else {}
    direct = clean(track.get("url") or share.get("href") or share.get("html"))
    if direct.startswith("https://www.shazam.com/") or direct.startswith("https://shazam.com/"):
        return direct
    return None


def shazam_to_meta(payload: Any) -> dict[str, Any] | None:
    data = _dump(payload)
    if not isinstance(data, dict):
        return None
    track = _dump(data.get("track"))
    if not isinstance(track, dict):
        return None
    title = clean(track.get("title"))
    artist = clean(track.get("subtitle") or track.get("artist"))
    if not title and not artist:
        return None
    fields = _section_fields(track)
    genres = track.get("genres") if isinstance(track.get("genres"), dict) else {}
    genre = clean(genres.get("primary") if isinstance(genres, dict) else "") or None
    images = track.get("images") if isinstance(track.get("images"), dict) else {}
    cover = clean(images.get("coverarthq") or images.get("coverart") or track.get("photo_url")) or None
    return {
        "title": title or None,
        "artist": artist or None,
        "album": fields.get("album"),
        "label": fields.get("label"),
        "year": year_from(fields.get("released") or fields.get("release date")),
        "genre": genre,
        "isrc": fields.get("isrc"),
        "cover_url": cover or None,
        "shazam_id": track.get("key"),
        "source_url": _shazam_url(track),
        "source": "shazam",
    }


async def recognize_shazam(shazam: Any, path: Path) -> dict[str, Any] | None:
    payload = await shazam.recognize(str(path))
    return shazam_to_meta(payload)


def identify_acoustid(path: Path, api_key: str) -> dict[str, Any] | None:
    if not api_key:
        return None
    import acoustid
    import musicbrainzngs

    musicbrainzngs.set_useragent("MusicIDTagger", "1.1", "https://github.com/robertvarga0123-design/music-id-tagger")
    try:
        results = list(acoustid.match(api_key, str(path)))
    except acoustid.NoBackendError as exc:
        raise RuntimeError("Az AcoustID-hez kell az fpcalc (Chromaprint) a gépen.") from exc
    if not results:
        return None
    score, recording_id, title, artist = results[0]
    if score < 0.5:
        return None
    meta: dict[str, Any] = {
        "title": title,
        "artist": artist,
        "mbid": recording_id,
        "score": score,
        "source_url": f"https://musicbrainz.org/recording/{recording_id}" if recording_id else None,
        "source": "acoustid",
    }
    try:
        rec = musicbrainzngs.get_recording_by_id(recording_id, includes=["artists", "releases", "tags"])
        recording = rec.get("recording", {})
        meta["title"] = recording.get("title") or title
        credits = recording.get("artist-credit") or []
        names = [
            item.get("artist", {}).get("name", "")
            for item in credits
            if isinstance(item, dict)
        ]
        joined = ", ".join(name for name in names if name)
        if joined:
            meta["artist"] = joined
        releases = recording.get("release-list") or []
        if releases:
            rel = releases[0]
            meta["album"] = rel.get("title")
            if rel.get("date"):
                meta["year"] = str(rel["date"])[:4]
        tags = recording.get("tag-list") or []
        genres = [tag.get("name") for tag in tags if tag.get("count", 0) > 0 and tag.get("name")]
        if genres:
            meta["genre"] = genres[0]
    except Exception:
        pass
    return meta
