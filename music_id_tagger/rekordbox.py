"""Read a Rekordbox XML library and write corrected track fields back into it."""

from __future__ import annotations

import os
import shutil
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import unquote, urlparse

from music_id_tagger.match import clean

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

_FIELDS = (
    ("Name", "title"),
    ("Artist", "artist"),
    ("Album", "album"),
    ("Genre", "genre"),
    ("Year", "year"),
    ("Label", "label"),
)


def location_to_path(location: str) -> Path | None:
    text = clean(location)
    if not text:
        return None
    if text.lower().startswith("file:"):
        parsed = urlparse(text)
        raw = unquote(parsed.path or "")
        if len(raw) >= 3 and raw[0] == "/" and raw[2] == ":":
            raw = raw[1:]
        return Path(raw) if raw else None
    return Path(text)


def collect_xml(paths: list[str]) -> list[Path]:
    found: list[Path] = []
    seen: set[str] = set()
    for raw in paths:
        path = Path(raw)
        candidates = [path] if path.is_file() else []
        for candidate in candidates:
            if candidate.suffix.lower() != ".xml":
                continue
            try:
                key = str(candidate.resolve())
            except OSError:
                continue
            if key in seen:
                continue
            seen.add(key)
            found.append(candidate)
    return found


def audio_from_xml(xmls: list[Path]) -> list[Path]:
    found: list[Path] = []
    seen: set[str] = set()
    for xml in xmls:
        try:
            root = ET.parse(xml).getroot()
        except (ET.ParseError, OSError):
            continue
        for track in root.findall("./COLLECTION/TRACK"):
            path = location_to_path(track.get("Location") or "")
            if path is None or not path.is_file():
                continue
            try:
                if path.stat().st_size < 32_000:
                    continue
                key = os.path.normcase(str(path.resolve()))
            except OSError:
                continue
            if key in seen:
                continue
            seen.add(key)
            found.append(path)
    return found


def _tonality(meta: dict) -> str:
    name = clean(meta.get("key_name"))
    if name:
        return name
    camelot = clean(meta.get("key")).upper()
    return CAMELOT_TO_NAME.get(camelot, clean(meta.get("key")))


def _year(value) -> str:
    digits = "".join(ch for ch in clean(value) if ch.isdigit())
    return digits[:4]


def _bpm_number(value) -> float | None:
    text = clean(value).replace(",", ".")
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def apply_track(track: ET.Element, meta: dict, keep_identity: bool, write_bpm: bool = True) -> list[str]:
    """Update one TRACK element. Returns the lines that actually changed."""
    changes: list[str] = []
    identity = {"Name", "Artist", "Album"}
    for attr, key in _FIELDS:
        incoming = _year(meta.get(key)) if key == "year" else clean(meta.get(key))
        if not incoming:
            continue
        current = clean(track.get(attr))
        if attr in identity and keep_identity and current:
            continue
        if current == incoming:
            continue
        track.set(attr, incoming)
        changes.append(f"{attr}: {current or '–'} → {incoming}")
    tone = _tonality(meta)
    if tone and clean(track.get("Tonality")) != tone:
        previous = clean(track.get("Tonality"))
        track.set("Tonality", tone)
        changes.append(f"Tonality: {previous or '–'} → {tone}")
    if write_bpm and meta.get("bpm") not in (None, ""):
        incoming = _bpm_number(meta.get("bpm"))
        current = _bpm_number(track.get("AverageBpm"))
        if incoming is not None and (current is None or abs(incoming - current) > 1.0):
            text = f"{incoming:.2f}"
            previous = clean(track.get("AverageBpm"))
            track.set("AverageBpm", text)
            changes.append(f"AverageBpm: {previous or '–'} → {text}")
            tempos = track.findall("TEMPO")
            if len(tempos) == 1:
                tempos[0].set("Bpm", text)
    ident = clean(meta.get("beatport_id"))
    if ident:
        stamp = f"Beatport ID: {ident}"
        current = clean(track.get("Comments"))
        if stamp not in current:
            track.set("Comments", f"{current} | {stamp}".strip(" |") if current else stamp)
            changes.append(f"Comments: {stamp}")
    return changes


def path_key(path: Path) -> str:
    return os.path.normcase(str(path.resolve()))


def update_library(
    path: Path,
    by_path: dict[str, dict],
    keep_identity: bool,
    dry_run: bool,
    write_bpm_to_xml: bool = True,
) -> tuple[int, int, list[str]]:
    tree = ET.parse(path)
    root = tree.getroot()
    changed = 0
    missing = 0
    notes: list[str] = []
    for track in root.findall("./COLLECTION/TRACK"):
        location = location_to_path(track.get("Location") or "")
        if location is None:
            continue
        if not location.is_file():
            missing += 1
            continue
        meta = by_path.get(path_key(location))
        if not meta:
            continue
        who = clean(track.get("Artist")) or clean(track.get("Name")) or location.name
        diffs = apply_track(track, meta, keep_identity, write_bpm=write_bpm_to_xml)
        if not diffs:
            continue
        changed += 1
        notes.append(f"{who}: " + "; ".join(diffs))
    if changed and not dry_run:
        backup = path.with_suffix(path.suffix + ".bak")
        shutil.copy2(path, backup)
        tree.write(path, encoding="UTF-8", xml_declaration=True)
    return changed, missing, notes
