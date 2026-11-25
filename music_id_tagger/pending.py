"""Search results waiting for a separate write step. Nothing here touches a file by itself."""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass, field
from pathlib import Path

from music_id_tagger.match import clean
from music_id_tagger.tags import changed_fields

FIELDS = {
    "bpm": ("bpm",),
    "key": ("key", "key_name"),
    "genre": ("genre",),
    "label": ("label",),
    "isrc": ("isrc",),
    "cover": ("cover_url",),
    "year": ("year",),
    "album": ("album",),
    "identity": ("title", "artist"),
}

_BAD_NAME = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


@dataclass
class Pending:
    path: str
    name: str
    status: str
    before: dict = field(default_factory=dict)
    after: dict = field(default_factory=dict)
    changed: dict = field(default_factory=dict)
    source: str = ""
    confidence: int = 0
    unsure: bool = False
    candidates: list = field(default_factory=list)
    source_url: str = ""
    source_label: str = ""
    fields: dict = field(default_factory=dict)
    duration: float | None = None

    def as_dict(self) -> dict:
        return {
            "path": self.path,
            "name": self.name,
            "status": self.status,
            "before": self.before,
            "after": self.after,
            "changed": self.changed,
            "source": self.source,
            "confidence": self.confidence,
            "unsure": self.unsure,
            "candidates": self.candidates,
            "source_url": self.source_url,
            "source_label": self.source_label,
            "fields": self.fields,
            "duration": self.duration,
        }


def field_enabled(name: str, enabled: dict | None, override: dict | None = None) -> bool:
    if override and name in override:
        return bool(override[name])
    if not enabled or name not in enabled:
        return True
    return bool(enabled[name])


def needs_lookup(tags: dict | None, enabled: dict | None, has_cover: bool = True) -> bool:
    """False when every enabled field is already filled. Those files skip the network."""
    data = tags or {}
    for name, keys in FIELDS.items():
        if not field_enabled(name, enabled):
            continue
        if name == "cover":
            if not has_cover:
                return True
            continue
        if name == "key":
            if not clean(data.get("key")):
                return True
            continue
        if any(not clean(data.get(key)) for key in keys):
            return True
    return False


def masked_after(
    change: Pending,
    enabled: dict | None,
    fill_missing: bool,
    key_style: str = "camelot",
    genre_map: dict | None = None,
) -> dict:
    """The dict that would actually be written. Disabled and already-filled fields stay."""
    from music_id_tagger.match import format_key

    proposed = dict(change.before)
    for name, keys in FIELDS.items():
        if not field_enabled(name, enabled, change.fields):
            continue
        for key in keys:
            if key not in change.after:
                continue
            value = change.after[key]
            if key == "key":
                value = format_key(value, key_style) or value
            if key == "genre":
                value = apply_genre_map(value, genre_map)
            if fill_missing and clean(change.before.get(key)):
                continue
            proposed[key] = value
    for key in ("beatport_id", "mix", "catalog", "source", "spotify_id"):
        if change.after.get(key) and (not fill_missing or not clean(change.before.get(key))):
            proposed[key] = change.after[key]
    return proposed


def preview_changes(
    change: Pending,
    enabled: dict | None,
    fill_missing: bool,
    key_style: str = "camelot",
    genre_map: dict | None = None,
) -> dict:
    return changed_fields(change.before, masked_after(change, enabled, fill_missing, key_style, genre_map))


def confidence_of(meta: dict | None, unsure: bool, status: str) -> int:
    if status in {"missed", "failed", "rejected"}:
        return 0
    if status == "skipped":
        return 100
    score = 0.0
    raw = (meta or {}).get("match_score")
    try:
        if raw not in (None, ""):
            score = float(raw)
    except (TypeError, ValueError):
        score = 0.0
    source = clean((meta or {}).get("source")).lower()
    if "beatport" in source and not unsure:
        return min(100, 80 + int(score // 10))
    if unsure:
        return 40 if score else 25
    return 70


def apply_genre_map(genre: str, table: dict | None) -> str:
    text = clean(genre)
    if not text or not isinstance(table, dict):
        return text
    for key, value in table.items():
        if clean(key).lower() == text.lower():
            mapped = clean(value)
            return mapped or text
    return text


def parse_genre_map(text: str) -> dict[str, str]:
    """Lines of ``Beatport címke -> saját címke``."""
    found: dict[str, str] = {}
    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "->" in line:
            left, right = line.split("->", 1)
        elif "\t" in line:
            left, right = line.split("\t", 1)
        else:
            continue
        source = clean(left)
        target = clean(right)
        if source and target:
            found[source] = target
    return found


def choose_candidate(change: Pending, index: int, key_style: str = "camelot", genre_map: dict | None = None) -> Pending:
    if index < 0 or index >= len(change.candidates):
        return change
    chosen = change.candidates[index] if isinstance(change.candidates[index], dict) else {}
    after = dict(change.after)
    for key in ("title", "artist", "mix", "bpm", "key", "genre", "cover_url", "beatport_id", "label", "isrc"):
        if chosen.get(key) not in (None, ""):
            after[key] = chosen[key]
    if after.get("key"):
        from music_id_tagger.match import format_key

        after["key"] = format_key(after["key"], key_style) or after["key"]
    if after.get("genre"):
        after["genre"] = apply_genre_map(str(after["genre"]), genre_map)
    after["source"] = "beatport"
    after["match_score"] = chosen.get("score") or chosen.get("match_score") or after.get("match_score")
    change.after = after
    change.changed = changed_fields(change.before, after)
    change.source = "beatport"
    change.source_url = clean(chosen.get("source_url")) or change.source_url
    change.unsure = False
    change.status = "ok"
    change.confidence = confidence_of(after, False, "ok")
    return change


def filter_pending(items: list[Pending], name: str) -> list[Pending]:
    wanted = clean(name).lower() or "all"
    if wanted == "unsure":
        return [item for item in items if item.unsure or item.status == "unsure"]
    if wanted == "missed":
        return [item for item in items if item.status == "missed"]
    if wanted == "failed":
        return [item for item in items if item.status == "failed"]
    if wanted == "changed":
        return [item for item in items if item.changed and item.status in {"ok", "unsure"}]
    return list(items)


def select_for_apply(items: list[Pending], mode: str, selected: list[str] | None = None) -> list[Pending]:
    """Rows the Apply buttons should write. Misses are never written."""
    usable = [item for item in items if item.status in {"ok", "unsure"}]
    wanted = clean(mode).lower()
    if wanted == "selected":
        paths = set(selected or [])
        return [item for item in usable if item.path in paths]
    if wanted == "sure":
        return [item for item in usable if not item.unsure]
    return usable


def summary_line(change: Pending) -> str:
    bits = []
    for key in ("artist", "title", "bpm", "key", "genre"):
        old = clean(change.before.get(key))
        new = clean(change.changed.get(key))
        if not new or new == old:
            continue
        bits.append(f"{old or '–'} → {new}" if key in {"artist", "title"} else f"{key} {new}")
    return " | ".join(bits) or "nincs változás"


def export_csv(items: list[Pending], dest: Path, only: str | None = None) -> int:
    rows = filter_pending(items, only or "all") if only else list(items)
    dest.parent.mkdir(parents=True, exist_ok=True)
    with dest.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["fájl", "állapot", "régi", "új", "forrás", "megbízhatóság"])
        for item in rows:
            old = " | ".join(clean(item.before.get(key)) for key in ("artist", "title") if clean(item.before.get(key)))
            new = " | ".join(clean(item.after.get(key)) for key in ("artist", "title", "bpm", "key", "genre") if clean(item.after.get(key)))
            writer.writerow([item.path, item.status, old, new, item.source, item.confidence])
    return len(rows)


def duplicate_groups(items: list[Pending]) -> list[dict]:
    """Groups that share an ISRC or a Beatport id. Nothing is deleted."""
    groups: list[dict] = []
    for kind, key in (("isrc", "isrc"), ("beatport_id", "beatport_id")):
        buckets: dict[str, list[Pending]] = {}
        for item in items:
            value = clean(item.after.get(key) or item.before.get(key)).upper()
            if not value:
                continue
            buckets.setdefault(value, []).append(item)
        for value, grouped in buckets.items():
            if len(grouped) < 2:
                continue
            durations = [item.duration for item in grouped if isinstance(item.duration, (int, float))]
            spread = max(durations) - min(durations) if len(durations) >= 2 else None
            groups.append(
                {
                    "kind": kind,
                    "value": value,
                    "files": [item.path for item in grouped],
                    "duration_spread": spread,
                    "duration_mismatch": spread is not None and spread > 6,
                }
            )
    return groups


def render_filename(template: str, meta: dict, ext: str) -> str:
    if not clean(template):
        return ""
    values = {
        "artist": clean(meta.get("artist")) or "Ismeretlen",
        "title": clean(meta.get("title")) or "Névtelen",
        "key": clean(meta.get("key")),
        "bpm": clean(meta.get("bpm")),
        "genre": clean(meta.get("genre")),
        "label": clean(meta.get("label")),
        "mix": clean(meta.get("mix")),
    }

    class _Safe(dict):
        def __missing__(self, key: str) -> str:
            return ""

    try:
        text = template.format_map(_Safe(values))
    except (IndexError, ValueError):
        return ""
    text = _BAD_NAME.sub("", text)
    text = re.sub(r"\s+", " ", text).strip(" .")
    if not text:
        return ""
    suffix = ext if ext.startswith(".") else f".{ext}"
    if not text.lower().endswith(suffix.lower()):
        text += suffix
    return text


def unique_target(directory: Path, name: str, reserved: set[str]) -> Path:
    dest = directory / name
    key = str(dest)
    if not dest.exists() and key not in reserved:
        reserved.add(key)
        return dest
    stem = Path(name).stem
    ext = Path(name).suffix
    number = 2
    while True:
        candidate = directory / f"{stem} ({number}){ext}"
        marker = str(candidate)
        if not candidate.exists() and marker not in reserved:
            reserved.add(marker)
            return candidate
        number += 1


def plan_renames(items: list[Pending], template: str) -> list[tuple[Pending, Path]]:
    if not clean(template):
        return []
    reserved: set[str] = set()
    planned: list[tuple[Pending, Path]] = []
    for item in items:
        path = Path(item.path)
        name = render_filename(template, item.after or item.before, path.suffix)
        if not name or name == path.name:
            continue
        dest = unique_target(path.parent, name, reserved)
        if dest != path:
            planned.append((item, dest))
    return planned


class LogBook:
    def __init__(self) -> None:
        self.lines: list[tuple[str, str]] = []

    def add(self, level: str, text: str) -> None:
        self.lines.append((level or "info", text))

    def filtered(self, level: str = "all") -> list[tuple[str, str]]:
        wanted = clean(level).lower() or "all"
        if wanted == "err":
            return [item for item in self.lines if item[0] == "err"]
        if wanted == "info":
            return [item for item in self.lines if item[0] in {"info", "ok"}]
        return list(self.lines)

    def text(self, level: str = "all") -> str:
        return "\n".join(f"[{level_name}] {message}" for level_name, message in self.filtered(level))


def eta_text(done: int, total: int, elapsed: float) -> str:
    if done <= 0 or total <= done or elapsed <= 0:
        return ""
    remain = elapsed / done * (total - done)
    minutes = int(remain // 60)
    seconds = int(remain % 60)
    return f"{minutes}:{seconds:02d}"


def apply_pending(items: list[Pending], options, log, xml_paths: list | None = None) -> int:
    """Write the approved rows. Search is not repeated."""
    from music_id_tagger.rekordbox import path_key, rewrite_locations, update_library
    from music_id_tagger.tags import write_tags
    from music_id_tagger.undo import begin_run, commit_run, record_rename

    begin_run()
    written = 0
    renamed: dict[str, str] = {}
    try:
        enabled = getattr(options, "enabled_fields", None) or {}
        fill_missing = bool(getattr(options, "fill_missing_only", False))
        embed = bool(getattr(options, "embed_cover", True))
        template = clean(getattr(options, "rename_template", ""))
        key_style = clean(getattr(options, "key_format", "")) or "camelot"
        genre_map = getattr(options, "genre_map", None) or {}
        reserved: set[str] = set()
        by_path: dict[str, dict] = {}
        renames: list[tuple[Pending, Path, Path, str]] = []
        for item in items:
            path = Path(item.path)
            if not path.is_file():
                log("err", f"Nincs meg a fájl: {item.name}")
                continue
            target = masked_after(item, enabled, fill_missing, key_style, genre_map)
            try:
                old_key = path_key(path)
            except OSError:
                old_key = str(path)
            delta = changed_fields(item.before, target)
            new_name = render_filename(template, target, path.suffix) if template else ""
            will_rename = bool(new_name and new_name != path.name)
            if not delta and not will_rename:
                continue
            if delta:
                try:
                    write_tags(path, target, False, embed and field_enabled("cover", enabled, item.fields))
                except Exception as exc:
                    log("err", f"Tag írás hiba ({item.name}): {exc}")
                    continue
                written += 1
                log("ok", f"ÍRVA: {item.name}")
            item.status = "applied"
            item.changed = delta
            by_path[old_key] = target
            if not will_rename:
                continue
            dest = unique_target(path.parent, new_name, reserved)
            renames.append((item, path, dest, old_key))
        if xml_paths:
            for xml in xml_paths:
                try:
                    update_library(
                        Path(xml),
                        by_path,
                        bool(getattr(options, "keep_identity", True)),
                        False,
                        bool(getattr(options, "write_bpm_to_xml", True)),
                    )
                except Exception as exc:
                    log("err", f"Rekordbox XML hiba ({Path(xml).name}): {exc}")
        for item, source, dest, old_key in renames:
            try:
                source.rename(dest)
            except OSError as exc:
                log("err", f"Átnevezés hiba ({source.name}): {exc}")
                continue
            record_rename(source, dest)
            renamed[old_key] = str(dest)
            item.path = str(dest)
            item.name = dest.name
            log("ok", f"Átnevezve: {source.name} → {dest.name}")
        if xml_paths and renamed:
            for xml in xml_paths:
                try:
                    rewrite_locations(Path(xml), renamed, False)
                except Exception as exc:
                    log("err", f"Rekordbox útvonal hiba ({Path(xml).name}): {exc}")
    finally:
        commit_run()
    return written
