import hashlib
from pathlib import Path

import pytest

from music_id_tagger.updatecheck import (
    INSTALLER_NAME,
    UpdateError,
    _installer_asset,
    allowed_download_url,
    check_update,
    fetch_verified,
    parse_sha256,
)

REPO_URL = "https://github.com/robertvarga0123-design/music-id-tagger/releases/download/v9.9.9/MusicIDTagger-Setup.exe"
GOOD = b"installer-bytes"


def _sha(payload: bytes = GOOD) -> str:
    return hashlib.sha256(payload).hexdigest()


class _Stream:
    def __init__(self, payload: bytes, url: str) -> None:
        self.payload = payload
        self.url = url

    def raise_for_status(self) -> None:
        return None

    def iter_content(self, chunk_size: int):
        yield self.payload

    def __enter__(self):
        return self

    def __exit__(self, *args) -> bool:
        return False


def _patch_download(monkeypatch, payload: bytes = GOOD):
    def fake_get(url, **kwargs):
        assert allowed_download_url(url)
        return _Stream(payload, url)

    monkeypatch.setattr("requests.get", fake_get)


def test_asset_name_is_exact_and_url_is_this_repo():
    assets = [
        {"name": "Other-Setup.exe", "browser_download_url": REPO_URL},
        {"name": INSTALLER_NAME, "browser_download_url": "https://evil.example/MusicIDTagger-Setup.exe"},
        {"name": INSTALLER_NAME, "browser_download_url": REPO_URL},
    ]
    chosen = _installer_asset(assets)
    assert chosen is not None
    assert chosen["name"] == INSTALLER_NAME
    assert chosen["browser_download_url"] == REPO_URL
    assert _installer_asset([{"name": "not-setup.exe", "browser_download_url": REPO_URL}]) is None
    assert allowed_download_url("https://github.com/other/music-id-tagger/releases/download/v1/x.exe") is False


def test_good_hash_keeps_a_unique_file(tmp_path, monkeypatch):
    _patch_download(monkeypatch)
    path = fetch_verified(REPO_URL, _sha(), directory=str(tmp_path))
    assert path.name == INSTALLER_NAME
    assert path.parent != tmp_path
    assert path.parent.name.startswith("MusicIDTagger-")
    assert path.read_bytes() == GOOD
    assert path.parent.parent == tmp_path


def test_bad_hash_deletes_the_file_and_does_not_launch(tmp_path, monkeypatch):
    _patch_download(monkeypatch)
    launched = []
    monkeypatch.setattr("music_id_tagger.updatecheck.launch_installer", lambda path: launched.append(path))
    with pytest.raises(UpdateError):
        fetch_verified(REPO_URL, "ab" * 32, directory=str(tmp_path))
    assert list(tmp_path.rglob(INSTALLER_NAME)) == []
    assert launched == []


def test_missing_hash_deletes_the_file(tmp_path, monkeypatch):
    _patch_download(monkeypatch)
    with pytest.raises(UpdateError):
        fetch_verified(REPO_URL, "", directory=str(tmp_path))
    assert list(tmp_path.rglob(INSTALLER_NAME)) == []
    assert parse_sha256("jegyzet\nSHA256: " + "cd" * 32 + "\n") == "cd" * 32
    assert parse_sha256("nincs hash") is None


def test_foreign_url_is_rejected_without_download(tmp_path, monkeypatch):
    def boom(*args, **kwargs):
        raise AssertionError("requests.get")

    monkeypatch.setattr("requests.get", boom)
    with pytest.raises(UpdateError):
        fetch_verified("https://evil.example/MusicIDTagger-Setup.exe", _sha(), directory=str(tmp_path))
    assert list(tmp_path.rglob("*")) == []


def test_check_update_returns_exact_asset_and_sha(monkeypatch):
    body = {
        "tag_name": "v9.9.9",
        "body": "SHA256: " + "ab" * 32,
        "assets": [
            {"name": "notes.txt", "browser_download_url": REPO_URL.replace(INSTALLER_NAME, "notes.txt")},
            {"name": INSTALLER_NAME, "browser_download_url": REPO_URL},
        ],
    }

    class Response:
        status_code = 200

        def json(self):
            return body

    monkeypatch.setattr("requests.get", lambda *args, **kwargs: Response())
    info = check_update("1.4.1")
    assert info is not None
    assert info["name"] == INSTALLER_NAME
    assert info["url"] == REPO_URL
    assert info["sha256"] == "ab" * 32
    assert Path(info["name"]).name == INSTALLER_NAME
