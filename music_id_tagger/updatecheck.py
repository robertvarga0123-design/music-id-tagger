"""Look up the newest GitHub release and download the Windows installer.

The installer is started only when its SHA-256 matches the ``SHA256:`` line in
the release notes, and only from this repository's GitHub download URL.
"""

from __future__ import annotations

import hashlib
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = "robertvarga0123-design/music-id-tagger"
INSTALLER_NAME = "MusicIDTagger-Setup.exe"
_API = f"https://api.github.com/repos/{REPO}/releases/latest"
_DOWNLOAD_PREFIX = f"https://github.com/{REPO}/releases/download/"
_SHA_LINE = re.compile(r"^SHA256:\s*([0-9a-fA-F]{64})\s*$", re.M)
_SHA = re.compile(r"^[0-9a-fA-F]{64}$")


class UpdateError(Exception):
    """The installer was not started."""


def parse_version(text: str) -> tuple[int, ...]:
    nums = re.findall(r"\d+", text or "")
    return tuple(int(item) for item in nums[:3]) or (0,)


def is_newer(remote: str, current: str) -> bool:
    return parse_version(remote) > parse_version(current)


def parse_sha256(body: str) -> str | None:
    match = _SHA_LINE.search(body or "")
    if not match:
        return None
    return match.group(1).lower()


def allowed_download_url(url: str) -> bool:
    return isinstance(url, str) and url.startswith(_DOWNLOAD_PREFIX)


def check_update(current: str) -> dict | None:
    """Return ``{version, url, name, sha256}`` when GitHub has a newer installer."""
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
    if not isinstance(body, dict):
        return None
    tag = str(body.get("tag_name") or "")
    if not is_newer(tag, current):
        return None
    asset = _installer_asset(body.get("assets") or [])
    if not asset:
        return None
    return {
        "version": tag.lstrip("vV"),
        "url": asset["browser_download_url"],
        "name": INSTALLER_NAME,
        "sha256": parse_sha256(str(body.get("body") or "")) or "",
    }


def _installer_asset(assets: list) -> dict | None:
    for asset in assets:
        if not isinstance(asset, dict):
            continue
        name = str(asset.get("name") or "")
        url = str(asset.get("browser_download_url") or "")
        if name == INSTALLER_NAME and allowed_download_url(url):
            return asset
    return None


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 256), b""):
            digest.update(chunk)
    return digest.hexdigest()


def download(url: str, dest: Path) -> None:
    import requests

    if not allowed_download_url(url):
        raise UpdateError("A frissítés címe nem a projekt GitHub kiadása, nem töltöm le.")
    dest.parent.mkdir(parents=True, exist_ok=True)
    temporary = dest.with_suffix(dest.suffix + ".part")
    try:
        with requests.get(url, stream=True, timeout=60, headers={"User-Agent": "MusicIDTagger"}) as response:
            response.raise_for_status()
            with temporary.open("wb") as handle:
                for chunk in response.iter_content(chunk_size=1024 * 256):
                    if chunk:
                        handle.write(chunk)
        temporary.replace(dest)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def _discard(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError:
        return
    parent = path.parent
    try:
        if parent.name.startswith("MusicIDTagger-") and not any(parent.iterdir()):
            parent.rmdir()
    except OSError:
        return


def fetch_verified(url: str, expected_sha: str, *, directory: str | None = None) -> Path:
    """Download the installer to a unique folder and keep it only if the hash matches.

    A missing or different hash deletes the file and raises. The caller launches
    nothing in that case.
    """
    if not allowed_download_url(url):
        raise UpdateError("A frissítés címe nem a projekt GitHub kiadása, nem töltöm le.")
    folder = Path(tempfile.mkdtemp(prefix="MusicIDTagger-", dir=directory))
    dest = folder / INSTALLER_NAME
    try:
        download(url, dest)
    except Exception:
        _discard(dest)
        raise
    expected = (expected_sha or "").strip().lower()
    if not _SHA.fullmatch(expected):
        _discard(dest)
        raise UpdateError("A kiadás leírásában nincs SHA256, a telepítőt töröltem, nem indítom el.")
    actual = sha256_file(dest)
    if actual != expected:
        _discard(dest)
        raise UpdateError("A telepítő SHA256-ja nem egyezik, töröltem, nem indítom el.")
    return dest


def installer_script(path: Path) -> str:
    """VBScript that waits, then opens the installer. No ``cmd /c start``.

    Python's list2cmdline turns ``start "" "C:\\setup.exe"`` into escaped
    quotes. cmd.exe then searches for ``\\`` and Windows shows
    „A Windows nem találja a következőt: '\\'”.
    """
    text = str(path).strip()
    if not text or text.strip("\\/") == "":
        raise UpdateError("A telepítő útvonala üres, nem indítom el.")
    if any(ord(char) < 32 for char in text):
        raise UpdateError("A telepítő útvonala hibás, nem indítom el.")
    literal = text.replace('"', '""')
    return f'WScript.Sleep 2000\r\nCreateObject("Shell.Application").ShellExecute "{literal}"\r\n'


def launch_installer(path: Path) -> None:
    """Start the installer after this process has a moment to exit."""
    if sys.platform != "win32":
        subprocess.Popen([str(path)], start_new_session=True)
        return
    script = installer_script(path)
    launcher = Path(path).with_name("indito.vbs")
    launcher.write_text(script, encoding="utf-16")
    os.startfile(str(launcher))  # noqa: S606  Windows-only, path is the verified installer folder

