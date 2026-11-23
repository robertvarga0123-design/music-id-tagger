"""Decide which catalog fields are safe to keep.

A fuzzy title hit must not overwrite BPM, key or genre. Beatport may replace
those DJ fields when the score is high enough and the tempo is not a half-time
twin of the value already on the file (70 vs 140). A hit whose length or cover
clearly disagrees with the file is dropped before any field is copied.
"""

from __future__ import annotations

import math

from music_id_tagger.covers import cover_conflict
from music_id_tagger.match import artists_compatible, camelot_name, clean, titles_compatible, to_camelot

_FILL = ("album", "year", "isrc", "cover_url", "label", "mbid", "spotify_id", "catalog", "mix", "duration")


def bpm_number(value) -> float | None:
    text = clean(value).replace(",", ".")
    if not text:
        return None
    try:
        number = float(text)
    except ValueError:
        return None
    if not math.isfinite(number) or number <= 0 or number > 400:
        return None
    return number


def bpm_half_time(existing, incoming) -> bool:
    """True when the two tempos are the same pulse an octave apart."""
    left = bpm_number(existing)
    right = bpm_number(incoming)
    if left is None or right is None:
        return False
    ratio = max(left, right) / min(left, right)
    return 1.9 <= ratio <= 2.1


def duration_seconds(value) -> float | None:
    """Seconds from a number or M:SS / H:MM:SS. Milliseconds stay the caller's job."""
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        if not math.isfinite(float(value)) or value <= 0 or value > 3 * 3600:
            return None
        return float(value)
    text = clean(value)
    if not text:
        return None
    if ":" in text:
        parts = text.split(":")
        try:
            nums = [float(part) for part in parts]
        except ValueError:
            return None
        if len(nums) == 2:
            total = nums[0] * 60 + nums[1]
        elif len(nums) == 3:
            total = nums[0] * 3600 + nums[1] * 60 + nums[2]
        else:
            return None
        if total <= 0 or total > 3 * 3600:
            return None
        return total
    try:
        return duration_seconds(float(text.replace(",", ".")))
    except ValueError:
        return None


def durations_compatible(left, right) -> bool | None:
    """None when either side is unknown. False when the tracks are different lengths.

    The slack is 6 seconds or 4% of the longer file, whichever is larger.
    That keeps encode rounding, and rejects a radio edit against an extended mix.
    """
    first = duration_seconds(left)
    second = duration_seconds(right)
    if first is None or second is None:
        return None
    diff = abs(first - second)
    limit = max(6.0, 0.04 * max(first, second))
    return diff <= limit


def track_seconds(track: dict) -> float | None:
    """Length of a raw catalog object, in seconds."""
    if not isinstance(track, dict):
        return None
    for key in ("length_ms", "duration_ms", "trackTimeMillis"):
        raw = track.get(key)
        if raw in (None, "", 0):
            continue
        try:
            return duration_seconds(float(raw) / 1000.0)
        except (TypeError, ValueError):
            continue
    if track.get("length") not in (None, "", 0):
        raw = track.get("length")
        if isinstance(raw, (int, float)) and not isinstance(raw, bool) and raw > 10000:
            return duration_seconds(float(raw) / 1000.0)
        return duration_seconds(raw)
    if track.get("duration") not in (None, "", 0):
        return duration_seconds(track.get("duration"))
    return None


def prefer_duration(tracks: list, file_duration) -> tuple[list, bool]:
    """Drop rows whose length clearly disagrees. The flag is True when any row was dropped."""
    if file_duration is None:
        return [item for item in tracks if isinstance(item, dict)], False
    kept = []
    dropped = False
    for track in tracks:
        if not isinstance(track, dict):
            continue
        seconds = track_seconds(track)
        if seconds is not None and durations_compatible(file_duration, seconds) is False:
            dropped = True
            continue
        kept.append(track)
    return kept, dropped


def _score(hit: dict) -> float:
    raw = hit.get("match_score")
    if raw in (None, ""):
        return 0.0
    try:
        return float(raw)
    except (TypeError, ValueError):
        return 0.0


def _add_source(found: dict, hit: dict) -> None:
    incoming = clean(hit.get("source"))
    if not incoming:
        return
    parts: list[str] = []
    previous = clean(found.get("source"))
    for token in f"{previous}+{incoming}".split("+"):
        if token and token not in parts:
            parts.append(token)
    if parts:
        found["source"] = "+".join(parts)


def merge_hit(
    found: dict,
    hit: dict,
    query_artist: str,
    query_title: str,
    *,
    audio: bool,
    file_duration=None,
    file_cover_hash: str | None = None,
) -> str:
    """Fold one catalog hit into ``found``.

    Returns ``accepted``, ``weak``, ``rejected``, ``duration`` or ``cover``.
    Weak, rejected, duration and cover change nothing.
    An audio fingerprint may keep a score of 12. A filename-only hit (``audio=False``)
    needs 16 before BPM, key or genre are touched.
    ``file_duration`` and ``file_cover_hash`` are optional. When either side is
    missing, that check is skipped.
    """
    score = _score(hit)
    exact = score >= 100
    title = clean(hit.get("title"))
    artist = clean(hit.get("artist"))
    compatible = bool(title and artist) and titles_compatible(query_title, title, clean(hit.get("mix"))) and artists_compatible(
        query_artist, artist
    )
    if not exact and not compatible:
        return "rejected"
    if not exact and score < 12:
        return "weak"

    reference = file_duration if file_duration not in (None, "") else found.get("duration")
    if durations_compatible(reference, hit.get("duration")) is False:
        return "duration"
    if cover_conflict(file_cover_hash, hit):
        return "cover"

    # Audio fingerprint: 12 is enough. Filename only: demand a clearer hit before DJ fields.
    dj_ok = exact or (audio and score >= 12) or ((not audio) and score >= 16)
    beatport = "beatport" in clean(hit.get("source")).lower()
    _add_source(found, hit)
    if score >= _score(found):
        found["match_score"] = score
    if not clean(found.get("title")) and title:
        found["title"] = title
    if not clean(found.get("artist")) and artist:
        found["artist"] = artist
    for key in _FILL:
        if key == "label" and beatport and dj_ok and hit.get(key):
            found[key] = hit[key]
            continue
        if hit.get(key) and not clean(found.get(key)):
            found[key] = hit[key]
    if dj_ok:
        key_text = clean(hit.get("key"))
        camelot = to_camelot(key_text) if key_text else None
        use_key = camelot or key_text
        if use_key and (not clean(found.get("key")) or beatport):
            found["key"] = use_key
        name = clean(hit.get("key_name"))
        if not name and camelot and key_text.upper() != camelot:
            name = camelot_name(camelot) or key_text
        if name and (not clean(found.get("key_name")) or beatport):
            found["key_name"] = name
        if hit.get("bpm") not in (None, "") and not bpm_half_time(found.get("bpm"), hit.get("bpm")):
            if not clean(found.get("bpm")) or beatport:
                found["bpm"] = hit["bpm"]
        if beatport and hit.get("genre"):
            found["genre"] = hit["genre"]
        if hit.get("beatport_id"):
            found["beatport_id"] = hit["beatport_id"]
    url = clean(hit.get("source_url"))
    current = clean(found.get("source_url"))
    if url.startswith("https://") and ("beatport.com" in url or not current.startswith("https://")):
        found["source_url"] = url
    return "accepted"
