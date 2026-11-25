"""SQLite cache of identification results. The key is path, size and mtime."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from music_id_tagger.config import settings_dir


def cache_path() -> Path:
    return settings_dir() / "cache.db"


def file_key(path: Path) -> tuple[str, int, int] | None:
    try:
        stat = path.stat()
        return str(path.resolve()), int(stat.st_size), int(stat.st_mtime_ns)
    except OSError:
        return None


def _connect() -> sqlite3.Connection:
    folder = settings_dir()
    folder.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(cache_path())
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS seen (
            path TEXT NOT NULL,
            size INTEGER NOT NULL,
            mtime_ns INTEGER NOT NULL,
            payload TEXT NOT NULL,
            source TEXT NOT NULL,
            unsure INTEGER NOT NULL,
            stored_at TEXT NOT NULL,
            PRIMARY KEY (path, size, mtime_ns)
        )
        """
    )
    return db


def lookup(path: Path) -> dict | None:
    ident = file_key(path)
    if ident is None or not cache_path().is_file():
        return None
    db = _connect()
    try:
        row = db.execute(
            "SELECT payload, source, unsure, stored_at FROM seen WHERE path = ? AND size = ? AND mtime_ns = ?",
            ident,
        ).fetchone()
    finally:
        db.close()
    if not row:
        return None
    try:
        payload = json.loads(row[0])
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    payload["source"] = row[1]
    payload["unsure"] = bool(row[2])
    payload["stored_at"] = row[3]
    return payload


def store(path: Path, payload: dict, source: str, unsure: bool) -> None:
    ident = file_key(path)
    if ident is None:
        return
    body = json.dumps(payload, ensure_ascii=False, default=str)
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    db = _connect()
    try:
        db.execute(
            """
            INSERT INTO seen (path, size, mtime_ns, payload, source, unsure, stored_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(path, size, mtime_ns) DO UPDATE SET
                payload = excluded.payload,
                source = excluded.source,
                unsure = excluded.unsure,
                stored_at = excluded.stored_at
            """,
            (*ident, body, source or "", 1 if unsure else 0, stamp),
        )
        db.commit()
    finally:
        db.close()


def clear() -> None:
    target = cache_path()
    if target.is_file():
        target.unlink()
