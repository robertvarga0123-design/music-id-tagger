"""Look up the newest GitHub release and download the Windows installer."""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

REPO = "robertvarga0123-design/music-id-tagger"
_API = f"https://api.github.com/repos/{REPO}/releases/latest"


def parse_version(text: str) -> tuple[int, ...]:
    nums = re.findall(r"\d+", text or "")
    return tuple(int(item) for item in nums[:3]) or (0,)


def is_newer(remote: str, current: str) -> bool:
    return parse_version(remote) > parse_version(current)


def check_update(current: str) -> dict | None:
    """Return ``{version, url, name}`` when GitHub has a newer installer, else None."""
    import requests

    try:
        response = requests.get(
            _API,
            headers={"Accept": "application/vnd.github+json", "User-Agent": "MusicIDTagger"},
            timeout=15,
        )
    except Exception:
        return None
    if response.status_code != 200:
        return None
    try:
        body = response.json()
    except Exception:
        return None
    tag = str(body.get("tag_name") or "")
    if not is_newer(tag, current):
        return None
    asset = _installer_asset(body.get("assets") or [])
    if not asset:
        return None
    return {"version": tag.lstrip("vV"), "url": asset["browser_download_url"], "name": asset.get("name") or "MusicIDTagger-Setup.exe"}


def _installer_asset(assets: list) -> dict | None:
    setup = None
    for asset in assets:
        if not isinstance(asset, dict):
            continue
        name = str(asset.get("name") or "")
        url = str(asset.get("browser_download_url") or "")
        if not url.startswith("https://"):
            continue
        if name.lower().endswith("-setup.exe") or "setup" in name.lower():
            return asset
        if name.lower().endswith(".exe"):
            setup = asset
    return setup


def download(url: str, dest: Path) -> None:
    import requests

    dest.parent.mkdir(parents=True, exist_ok=True)
    temporary = dest.with_suffix(dest.suffix + ".part")
    with requests.get(url, stream=True, timeout=60, headers={"User-Agent": "MusicIDTagger"}) as response:
        response.raise_for_status()
        with temporary.open("wb") as handle:
            for chunk in response.iter_content(chunk_size=1024 * 256):
                if chunk:
                    handle.write(chunk)
    temporary.replace(dest)


def launch_installer(path: Path) -> None:
    """Start the installer after this process has a moment to exit."""
    if sys.platform == "win32":
        command = f'timeout /t 2 /nobreak >nul & start "" "{path}"'
        subprocess.Popen(["cmd", "/c", command], close_fds=True)
        return
    subprocess.Popen([str(path)], start_new_session=True)
