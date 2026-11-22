from __future__ import annotations

import json
import os
from pathlib import Path

SETTINGS_NAME = "settings.json"


def settings_dir() -> Path:
    base = os.environ.get("APPDATA")
    if base:
        return Path(base) / "MusicIDTagger"
    return Path.home() / ".music-id-tagger"


def settings_path() -> Path:
    return settings_dir() / SETTINGS_NAME


def load_settings() -> dict:
    path = settings_path()
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def save_settings(data: dict) -> None:
    clean = dict(data)
    clean.pop("beatport_password", None)
    clean.pop("password", None)
    clean.pop("spotify_client_secret", None)
    clean.pop("client_secret", None)
    folder = settings_dir()
    folder.mkdir(parents=True, exist_ok=True)
    settings_path().write_text(
        json.dumps(clean, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
