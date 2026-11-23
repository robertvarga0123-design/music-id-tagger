"""Undo log for tag writes.

Each tagging run stores one JSON file under settings_dir()/undo/.
The file lists every audio file that was written, with the fields from
before and after the write. Cover art is not stored and is not restored:
embedding a cover is one-way in this log.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Callable

_open_items: list[dict] | None = None


def begin_run() -> None:
    global _open_items
    _open_items = []


def commit_run() -> Path | None:
    global _open_items
    items = _open_items
    _open_items = None
    if not items:
        return None
    return _write(items)


def record(path: Path, before: dict, after: dict) -> Path | None:
    stat = path.stat()
    item = {
        "path": str(path),
        "mtime": stat.st_mtime,
        "mtime_ns": stat.st_mtime_ns,
        "ext": path.suffix.lower(),
        "before": dict(before),
        "after": dict(after),
    }
    if _open_items is not None:
        _open_items.append(item)
        return None
    return _write([item])


def list_runs() -> list[Path]:
    from music_id_tagger.config import settings_dir

    folder = settings_dir() / "undo"
    if not folder.is_dir():
        return []
    return sorted(folder.glob("*.json"), reverse=True)


def revert(run_file: Path, log: Callable[[str, str], None], confirm: Callable[[Path], bool] | None = None) -> int:
    """Restore fields this program wrote. Returns how many files were restored.

    If the file's mtime changed since the log was written, confirm(path) is
    asked. With confirm is None the file is skipped and reported.
    """
    from music_id_tagger.tags import SNAPSHOT_KEYS, restore_tags

    payload = json.loads(Path(run_file).read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError("Az undo fájl nem lista.")
    restored = 0
    for item in payload:
        if not isinstance(item, dict):
            continue
        path = Path(str(item.get("path") or ""))
        if not path.is_file():
            log("err", f"Nincs meg a fájl: {path}")
            continue
        current = path.stat().st_mtime_ns
        stored = int(item.get("mtime_ns") or 0)
        if stored and current != stored:
            log("muted", f"Megváltozott a címkézés óta: {path.name}")
            if confirm is None or not confirm(path):
                log("muted", f"Kihagyva: {path.name}")
                continue
        before = item.get("before") if isinstance(item.get("before"), dict) else {}
        after = item.get("after") if isinstance(item.get("after"), dict) else {}
        fields = {
            key: str(before.get(key) or "")
            for key in SNAPSHOT_KEYS
            if str(before.get(key) or "") != str(after.get(key) or "")
        }
        if not fields:
            log("muted", f"Nincs visszaállítható mező: {path.name}")
            continue
        restore_tags(path, fields)
        restored += 1
        log("ok", f"Visszaállítva: {path.name}")
    return restored


def _write(items: list[dict]) -> Path:
    from music_id_tagger.config import settings_dir

    folder = settings_dir() / "undo"
    folder.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%dT%H%M%S%f")
    dest = folder / f"{stamp}.json"
    tmp = dest.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(dest)
    return dest
