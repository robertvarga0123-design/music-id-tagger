from __future__ import annotations

import re
from typing import Any

_TOKEN = re.compile(r"[a-z0-9]+", re.I)
_FILENAME = re.compile(
    r"^(?:\d{1,3}[\s._-]*)?(?P<artist>.+?)\s+-\s+(?P<title>.+?)(?:\s*\[[^\]]*\])?$"
)
_STOP = {
    "the",
    "a",
    "an",
    "feat",
    "ft",
    "featuring",
    "and",
    "vs",
    "remix",
    "mix",
    "original",
    "extended",
}


def clean(value: Any) -> str:
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value)).strip()


def beatport_genre(genre: str | None, sub_genre: str | None) -> str | None:
    """A Beatport genre.name gyakran már kész DJ-címke: Techno (Peak Time / Driving)."""
    main = clean(genre)
    sub = clean(sub_genre)
    if main and "(" in main:
        return main
    if main and sub and sub.lower() not in main.lower():
        return f"{main} ({sub})"
    return main or sub or None


def camelot_or_name(key: Any) -> str | None:
    if isinstance(key, dict):
        number = key.get("camelot_number")
        letter = clean(key.get("camelot_letter"))
        if number not in (None, "") and letter:
            return f"{number}{letter}"
        name = clean(key.get("name"))
        return name or None
    text = clean(key)
    return text or None


def musical_key_name(key: Any) -> str | None:
    if isinstance(key, dict):
        name = clean(key.get("name"))
        return name or None
    return None


def _tokens(text: str) -> set[str]:
    return {t.lower() for t in _TOKEN.findall(text) if len(t) > 1 and t.lower() not in _STOP}


def _flat(text: str) -> str:
    text = clean(text).lower().replace("'", "").replace("'", "").replace("`", "")
    text = re.sub(r"\([^)]*\)", " ", text)
    text = re.sub(r"\b(original|extended|radio|club|dub)\s+mix\b", " ", text)
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return clean(text)


def titles_compatible(query: str, name: str, mix: str = "") -> bool:
    wanted = _flat(query)
    got = _flat(name)
    if not wanted or not got:
        return False
    if wanted == got or wanted in _flat(f"{name} {mix}") or got in wanted:
        return True
    overlap = _tokens(wanted) & _tokens(got)
    query_tokens = _tokens(wanted)
    if not query_tokens or not overlap:
        return False
    return len(overlap) / len(query_tokens) >= 0.6


def artists_compatible(query: str, artists: str) -> bool:
    wanted = _flat(query)
    got = _flat(artists)
    if not wanted or not got:
        return False
    if wanted in got or got in wanted:
        return True
    return bool(_tokens(wanted) & _tokens(got))


def score_track(track: dict, artist: str, title: str) -> int:
    name = clean(track.get("name"))
    mix = clean(track.get("mix_name"))
    artists = " ".join(
        clean(item.get("name"))
        for item in (track.get("artists") or [])
        if isinstance(item, dict)
    )
    full = f"{name} {mix}".strip()
    if not titles_compatible(title, name, mix) or not artists_compatible(artist, artists):
        return -1
    score = 0
    title_l = clean(title).lower()
    artist_l = clean(artist).lower()
    if title_l and title_l == name.lower():
        score += 8
    elif title_l and (title_l in full.lower() or name.lower() in title_l):
        score += 5

    title_tokens = _tokens(title)
    name_tokens = _tokens(full)
    if title_tokens and name_tokens:
        overlap = title_tokens & name_tokens
        score += 2 * len(overlap)
        if title_tokens <= name_tokens:
            score += 3
        elif not overlap:
            score -= 3

    artist_tokens = _tokens(artist)
    art_tokens = _tokens(artists)
    if artist_tokens and art_tokens:
        overlap_a = artist_tokens & art_tokens
        score += 3 * len(overlap_a)
        if not overlap_a:
            score -= 4
    if artist_l and artist_l in artists.lower():
        score += 4
    return score


def best_track(tracks: list, artist: str, title: str, minimum: int = 5) -> tuple[dict | None, int]:
    best: dict | None = None
    best_score = 0
    for track in tracks:
        if not isinstance(track, dict):
            continue
        current = score_track(track, artist, title)
        if best is None or current > best_score:
            best = track
            best_score = current
    if best is None or best_score < minimum:
        return None, best_score
    return best, best_score


def is_uncertain(meta: dict | None, guessed: bool = False) -> bool:
    """True when the hit should be checked by hand.

    A Shazam or AcoustID audio match plus a strong catalog score is sure.
    A filename guess, a weak score, or no source at all is not.
    """
    data = meta or {}
    source = clean(data.get("source")).lower()
    audio = "shazam" in source or "acoustid" in source
    catalog = "beatport" in source or "spotify" in source
    if not audio and not catalog:
        return True
    if guessed and not audio:
        return True
    raw = data.get("match_score")
    if raw in (None, ""):
        return False
    try:
        score = float(raw)
    except (TypeError, ValueError):
        return True
    return score < 12


def parse_filename(filename: str) -> tuple[str, str] | None:
    stem = filename
    for ext in (
        ".mp3",
        ".flac",
        ".wav",
        ".aiff",
        ".aif",
        ".m4a",
        ".mp4",
        ".ogg",
        ".opus",
        ".aac",
    ):
        if stem.lower().endswith(ext):
            stem = stem[: -len(ext)]
            break
    stem = stem.replace("_", " ").strip()
    match = _FILENAME.match(stem)
    if not match:
        return None
    artist = clean(match.group("artist"))
    title = clean(match.group("title"))
    if len(artist) < 2 or len(title) < 2:
        return None
    return artist, title


def year_from(value: Any) -> str | None:
    text = clean(value)
    match = re.search(r"(19|20)\d{2}", text)
    return match.group(0) if match else None
