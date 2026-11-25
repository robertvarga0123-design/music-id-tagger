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


def load_password(data: dict | None = None) -> str:
    return _load_secret(data, "beatport_password_dpapi")


def load_spotify_secret(data: dict | None = None) -> str:
    return _load_secret(data, "spotify_client_secret_dpapi")


def load_grok_key(data: dict | None = None) -> str:
    return _load_secret(data, "grok_key_dpapi")


def load_gemini_key(data: dict | None = None) -> str:
    return _load_secret(data, "gemini_key_dpapi")


def _load_secret(data: dict | None, key: str) -> str:
    source = data if data is not None else load_settings()
    token = source.get(key)
    if not isinstance(token, str) or not token:
        return ""
    try:
        return _unprotect(token)
    except Exception:
        return ""


def save_settings(data: dict) -> None:
    previous = load_settings()
    clean = dict(data)
    remember = clean.get("remember_secrets", True)
    fields = (
        ("beatport_password", "beatport_password_dpapi"),
        ("spotify_client_secret", "spotify_client_secret_dpapi"),
        ("grok_key", "grok_key_dpapi"),
        ("gemini_key", "gemini_key_dpapi"),
    )
    clean.pop("password", None)
    clean.pop("client_secret", None)
    if remember is False:
        for field, blob_name in fields:
            clean.pop(field, None)
            clean.pop(blob_name, None)
    else:
        for field, blob_name in fields:
            _store_secret(clean, previous, field, blob_name)
    folder = settings_dir()
    folder.mkdir(parents=True, exist_ok=True)
    settings_path().write_text(
        json.dumps(clean, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _store_secret(clean: dict, previous: dict, field: str, blob_name: str) -> None:
    """Remember a secret with DPAPI. An empty field keeps the saved one."""
    secret = clean.pop(field, None)
    if isinstance(secret, str) and secret:
        token = _protect(secret)
        if token:
            clean[blob_name] = token
            return
    old = previous.get(blob_name)
    if isinstance(old, str) and old:
        clean[blob_name] = old
    else:
        clean.pop(blob_name, None)


def _protect(secret: str) -> str:
    import sys

    if sys.platform != "win32" or not secret:
        return ""
    import base64
    import ctypes
    from ctypes import wintypes

    class DATA_BLOB(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

    raw = secret.encode("utf-8")
    buf = ctypes.create_string_buffer(raw)
    incoming = DATA_BLOB(len(raw), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))
    outgoing = DATA_BLOB()
    if not ctypes.windll.crypt32.CryptProtectData(
        ctypes.byref(incoming), "MusicIDTagger", None, None, None, 0, ctypes.byref(outgoing)
    ):
        return ""
    try:
        encrypted = ctypes.string_at(outgoing.pbData, outgoing.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(outgoing.pbData)
    return base64.b64encode(encrypted).decode("ascii")


def _unprotect(token: str) -> str:
    import sys

    if sys.platform != "win32" or not token:
        return ""
    import base64
    import ctypes
    from ctypes import wintypes

    class DATA_BLOB(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

    raw = base64.b64decode(token)
    buf = ctypes.create_string_buffer(raw)
    incoming = DATA_BLOB(len(raw), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))
    outgoing = DATA_BLOB()
    if not ctypes.windll.crypt32.CryptUnprotectData(
        ctypes.byref(incoming), None, None, None, None, 0, ctypes.byref(outgoing)
    ):
        return ""
    try:
        return ctypes.string_at(outgoing.pbData, outgoing.cbData).decode("utf-8")
    finally:
        ctypes.windll.kernel32.LocalFree(outgoing.pbData)
