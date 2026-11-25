"""Find a Beatport track link on the open web when the catalog search misses.

Google often answers this network with a block page, so the lookup uses Bing's
HTML results and reads Beatport track URLs out of them. A miss is not an error.
"""

from __future__ import annotations

import base64
import re
from typing import Callable
from urllib.parse import quote_plus, unquote

_TRACK = re.compile(r"beatport\.com/(?:[a-z]{2}/)?track/[^/?#\"'\\s<>]+/(\d+)", re.I)
_B64 = re.compile(r"aHR0[A-Za-z0-9_\-]{16,}")


def beatport_ids_from_html(html: str) -> list[str]:
    text = unquote(html or "")
    found: list[str] = []

    def take(blob: str) -> None:
        for ident in _TRACK.findall(blob):
            if ident not in found:
                found.append(ident)

    take(text)
    for blob in _B64.findall(text):
        padded = blob + "=" * (-len(blob) % 4)
        try:
            decoded = base64.urlsafe_b64decode(padded).decode("utf-8", "replace")
        except Exception:
            continue
        take(unquote(decoded))
    return found[:5]


def beatport_ids(artist: str, title: str, log: Callable[[str, str], None] | None = None) -> list[str]:
    from music_id_tagger.match import clean
    from music_id_tagger.net import session_get

    who = clean(artist)
    name = clean(title)
    if not who or not name:
        return []
    query = quote_plus(f'"{who}" "{name}" beatport')
    url = f"https://www.bing.com/search?q={query}"
    import requests

    session = requests.Session()
    response = session_get(
        session,
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            "Accept-Language": "en-US,en;q=0.9,hu;q=0.8",
        },
        timeout=15,
        attempts=2,
    )
    if response is None or response.status_code != 200 or not response.text:
        if log:
            log("muted", "Webes keresés: a kereső most nem válaszolt.")
        return []
    ids = beatport_ids_from_html(response.text)
    if not ids and log:
        log("muted", f"Webes keresés: nincs Beatport link — {who} - {name}")
    return ids
