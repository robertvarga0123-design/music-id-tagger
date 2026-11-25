from __future__ import annotations

import re
from typing import Any

_TOKEN = re.compile(r"[a-z0-9]+", re.I)
_FILENAME = re.compile(
    r"^(?:\d{1,3}[\s._-]*)?(?P<artist>.+?)\s+-\s+(?P<title>.+?)(?:\s*\[[^\]]*\])?$"
)
_CAMELOT = re.compile(r"^(?P<num>\d{1,2})\s*(?P<letter>[ab])$", re.I)
_OPEN_KEY = re.compile(r"^(?P<num>\d{1,2})\s*(?P<letter>[md])$", re.I)
_MUSICAL = re.compile(
    r"^(?P<note>c#|db|d#|eb|f#|gb|g#|ab|a#|bb|[a-g])\s*(?P<mode>minor|min|major|maj|m)?$",
    re.I,
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
    "dj",
    "mc",
    "presents",
    "pres",
    "aka",
}

# Shazam és az Apple gyakran csak ennyit mond. Ez nem DJ-stílus.
GENERIC_GENRES = ("Dance", "Pop", "Electronic", "Electronica", "Music")


def genre_is_generic(value: Any) -> bool:
    """True when the label is only a broad consumer genre, not a DJ style."""
    text = clean(value)
    if not text:
        return False
    for word in GENERIC_GENRES:
        if re.search(rf"(?i)(?<![0-9A-Za-z]){re.escape(word)}(?![0-9A-Za-z])", text):
            return True
    return False


# Camelot wheel. Open Key 1m/1d sits on 8A/8B (A minor / C major).
CAMELOT_TO_NAME = {
    "1A": "G#m",
    "2A": "D#m",
    "3A": "A#m",
    "4A": "Fm",
    "5A": "Cm",
    "6A": "Gm",
    "7A": "Dm",
    "8A": "Am",
    "9A": "Em",
    "10A": "Bm",
    "11A": "F#m",
    "12A": "C#m",
    "1B": "B",
    "2B": "F#",
    "3B": "C#",
    "4B": "G#",
    "5B": "D#",
    "6B": "A#",
    "7B": "F",
    "8B": "C",
    "9B": "G",
    "10B": "D",
    "11B": "A",
    "12B": "E",
}
_MINOR = {
    "g#": "1A",
    "ab": "1A",
    "d#": "2A",
    "eb": "2A",
    "a#": "3A",
    "bb": "3A",
    "f": "4A",
    "c": "5A",
    "g": "6A",
    "d": "7A",
    "a": "8A",
    "e": "9A",
    "b": "10A",
    "f#": "11A",
    "gb": "11A",
    "c#": "12A",
    "db": "12A",
}
_MAJOR = {
    "b": "1B",
    "f#": "2B",
    "gb": "2B",
    "c#": "3B",
    "db": "3B",
    "g#": "4B",
    "ab": "4B",
    "d#": "5B",
    "eb": "5B",
    "a#": "6B",
    "bb": "6B",
    "f": "7B",
    "c": "8B",
    "g": "9B",
    "d": "10B",
    "a": "11B",
    "e": "12B",
}


def clean(value: Any) -> str:
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value)).strip()


def undouble(text: str) -> str:
    """Collapse ``Marie Vaunt Marie Vaunt`` into ``Marie Vaunt``.

    Some DJ exports write the artist twice in the filename, with a space
    and no extra dash. Halving stops when the two halves are no longer the same.
    """
    current = clean(text)
    while True:
        parts = current.split(" ")
        if len(parts) < 2 or len(parts) % 2:
            return current
        half = len(parts) // 2
        if parts[:half] != parts[half:]:
            return current
        current = " ".join(parts[:half])


def beatport_genre(genre: str | None, sub_genre: str | None) -> str | None:
    """A Beatport genre.name gyakran már kész DJ-címke: Techno (Peak Time / Driving)."""
    main = clean(genre)
    sub = clean(sub_genre)
    if main and "(" in main:
        return main
    if main and sub and sub.lower() not in main.lower():
        return f"{main} ({sub})"
    return main or sub or None


def to_camelot(value: Any) -> str | None:
    """Camelot, Open Key (1m/1d) or a musical name (Amin, F# minor) → 8A.

    Unrecognised text is None. A Beatport dict without a Camelot code is left
    to ``camelot_or_name``, which still returns the original name.
    """
    text = clean(value).replace(" ", "")
    if not text:
        return None
    camelot = _CAMELOT.match(text)
    if camelot:
        number = int(camelot.group("num"))
        if 1 <= number <= 12:
            return f"{number}{camelot.group('letter').upper()}"
        return None
    opened = _OPEN_KEY.match(text)
    if opened:
        number = int(opened.group("num"))
        if 1 <= number <= 12:
            camelot_num = ((8 - 1 + (number - 1)) % 12) + 1
            side = "A" if opened.group("letter").lower() == "m" else "B"
            return f"{camelot_num}{side}"
        return None
    musical = _MUSICAL.match(text)
    if not musical:
        spaced = clean(value)
        musical = _MUSICAL.match(re.sub(r"\s+", "", spaced))
    if not musical:
        return None
    note = musical.group("note").lower()
    mode = (musical.group("mode") or "").lower()
    minor = mode in {"m", "min", "minor"}
    table = _MINOR if minor else _MAJOR
    return table.get(note)


def camelot_name(code: Any) -> str | None:
    text = clean(code).upper().replace(" ", "")
    return CAMELOT_TO_NAME.get(text) or None


def camelot_or_name(key: Any) -> str | None:
    if isinstance(key, dict):
        number = key.get("camelot_number")
        letter = clean(key.get("camelot_letter"))
        if number not in (None, "") and letter:
            return f"{number}{letter}"
        raw = key.get("camelot")
        converted = to_camelot(raw) if raw not in (None, "") else None
        if converted:
            return converted
        name = clean(key.get("name"))
        return name or None
    text = clean(key)
    if not text:
        return None
    return to_camelot(text) or text


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
    if wanted == got:
        return True
    # A short title such as "Go" must not match inside "Let It Go".
    if len(wanted) < 4 or len(got) < 4:
        return False
    if wanted in _flat(f"{name} {mix}") or got in wanted:
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


def same_recording(artist: str, title: str, other_artist: str, other_title: str) -> bool:
    """True when two names are the same track, not merely a shared word."""
    if not clean(artist) or not clean(title) or not clean(other_artist) or not clean(other_title):
        return False
    return titles_compatible(title, other_title) and artists_compatible(artist, other_artist)


def fingerprint_allowed(hit_artist: str, hit_title: str, existing: dict | None, filename: str) -> bool:
    """A Shazam or AcoustID hit must agree with the filename and the tags, when those exist.

    A file named ``Matt Guy - Chorale.mp3`` must not become ``bbno$ - check``.
    If neither the tags nor the filename name a track, the fingerprint is the only clue.
    """
    anchors: list[tuple[str, str]] = []
    tags = existing or {}
    tag_artist = undouble(clean(tags.get("artist")))
    tag_title = undouble(clean(tags.get("title")))
    if tag_artist and tag_title:
        anchors.append((tag_artist, tag_title))
    parsed = parse_filename(filename or "")
    if parsed:
        anchors.append(parsed)
    if not anchors:
        return True
    return all(same_recording(hit_artist, hit_title, artist, title) for artist, title in anchors)


def search_identity(existing: dict | None, filename: str) -> tuple[str, str, str]:
    """Local artist and title to search with.

    Returns ``(artist, title, origin)``. Origin is ``tag``, ``file``,
    ``conflict-file`` or ``""``. When the tag and the filename name different
    tracks, the filename wins: a bad write must not hide the name on disk.
    """
    tags = existing or {}
    tag_artist = undouble(clean(tags.get("artist")))
    tag_title = undouble(clean(tags.get("title")))
    parsed = parse_filename(filename or "")
    has_tag = bool(tag_artist and tag_title)
    if has_tag and parsed and not same_recording(tag_artist, tag_title, parsed[0], parsed[1]):
        return parsed[0], parsed[1], "conflict-file"
    if has_tag:
        return tag_artist, tag_title, "tag"
    if parsed:
        return parsed[0], parsed[1], "file"
    return "", "", ""


def is_uncertain(meta: dict | None, guessed: bool = False) -> bool:
    """True when the hit should be checked by hand.

    A Shazam or AcoustID audio match plus a strong catalog score is sure.
    A fingerprint with no catalog, a filename guess, a weak score, or no source is not.
    """
    data = meta or {}
    source = clean(data.get("source")).lower()
    audio = "shazam" in source or "acoustid" in source
    catalog = "beatport" in source or "spotify" in source
    if not audio and not catalog:
        return True
    if audio and not catalog:
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
    artist = undouble(clean(match.group("artist")))
    title = undouble(clean(match.group("title")))
    if len(artist) < 2 or len(title) < 2:
        return None
    return artist, title


def year_from(value: Any) -> str | None:
    text = clean(value)
    match = re.search(r"(19|20)\d{2}", text)
    return match.group(0) if match else None
