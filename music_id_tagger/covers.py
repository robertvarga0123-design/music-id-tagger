"""Perceptual cover check. Missing art never rejects a hit."""

from __future__ import annotations

_cache: dict[str, str] = {}
_http = None


def cover_hash(data: bytes | None) -> str | None:
    """64-bit dHash. None when the bytes are not a readable image."""
    if not data or len(data) < 32 or len(data) > 5_000_000:
        return None
    try:
        import io

        from PIL import Image
    except Exception:
        return None
    try:
        image = Image.open(io.BytesIO(data)).convert("L")
        image = image.resize((9, 8), Image.Resampling.BILINEAR)
    except Exception:
        return None
    pixels = list(image.get_flattened_data() if hasattr(image, "get_flattened_data") else image.getdata())
    bits: list[str] = []
    for row in range(8):
        for col in range(8):
            left = pixels[row * 9 + col]
            right = pixels[row * 9 + col + 1]
            bits.append("1" if left > right else "0")
    return "".join(bits)


def hashes_differ(left: str | None, right: str | None) -> bool:
    """True only when both hashes exist and the pictures clearly differ."""
    if not left or not right or len(left) != len(right):
        return False
    distance = sum(bit_a != bit_b for bit_a, bit_b in zip(left, right))
    return distance > 12


def cover_hash_from_url(url: str) -> str | None:
    if not url.startswith("https://"):
        return None
    cached = _cache.get(url)
    if cached is not None:
        return cached or None
    digest = _download_hash(url)
    _cache[url] = digest or ""
    return digest


def cover_conflict(file_hash: str | None, hit: dict) -> bool:
    """True when the file already has art and the hit's cover is a different picture."""
    if not file_hash or not isinstance(hit, dict):
        return False
    remote = str(hit.get("cover_hash") or "")
    if not remote:
        url = str(hit.get("cover_url") or "")
        remote = cover_hash_from_url(url) or ""
        if remote:
            hit["cover_hash"] = remote
    return hashes_differ(file_hash, remote)


def _download_hash(url: str) -> str | None:
    global _http
    try:
        if _http is None:
            import requests

            from music_id_tagger.net import USER_AGENT

            _http = requests.Session()
            _http.headers["User-Agent"] = USER_AGENT
        from music_id_tagger.net import session_get

        response = session_get(_http, url, timeout=15, attempts=2)
    except Exception:
        return None
    if response is None or response.status_code != 200 or not response.content:
        return None
    mime = str(response.headers.get("Content-Type") or "")
    if mime and not mime.startswith("image/") and "octet-stream" not in mime:
        return None
    return cover_hash(response.content)
