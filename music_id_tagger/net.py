"""Shared HTTP helper. Retries the blips that used to abort a whole file."""

from __future__ import annotations

import time

USER_AGENT = "MusicIDTagger/1.2 (https://github.com/robertvarga0123-design/music-id-tagger)"
_RETRY = {429, 500, 502, 503, 504}


def session_get(session, url: str, *, params=None, headers=None, timeout: float = 20, attempts: int = 3):
    """GET with a short backoff. Returns the last response, or None if the network failed."""
    last = None
    for attempt in range(attempts):
        try:
            last = session.get(url, params=params, headers=headers, timeout=timeout)
        except Exception:
            last = None
            if attempt + 1 < attempts:
                time.sleep(0.4 * (attempt + 1))
            continue
        if last.status_code in _RETRY and attempt + 1 < attempts:
            time.sleep(0.6 * (attempt + 1))
            continue
        return last
    return last
