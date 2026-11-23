"""Decide which catalog fields are safe to keep.

A fuzzy title hit must not overwrite BPM, key or genre. Beatport may replace
those DJ fields when the score is high enough and the tempo is not a half-time
twin of the value already on the file (70 vs 140).
"""

from __future__ import annotations

import math

from music_id_tagger.match import artists_compatible, clean, titles_compatible

_FILL = ("album", "year", "isrc", "cover_url", "label", "mbid", "spotify_id", "catalog", "mix")


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


def merge_hit(found: dict, hit: dict, query_artist: str, query_title: str, *, audio: bool) -> str:
    """Fold one catalog hit into ``found``.

    Returns ``accepted``, ``weak`` or ``rejected``. Weak and rejected change nothing.
    An audio fingerprint may keep a score of 12. A filename-only hit (``audio=False``)
    needs 16 before BPM, key or genre are touched.
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
        for key in ("key", "key_name"):
            if not hit.get(key):
                continue
            if clean(found.get(key)) and not beatport:
                continue
            found[key] = hit[key]
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
