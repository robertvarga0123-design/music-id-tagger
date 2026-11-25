import asyncio
from pathlib import Path

import pytest

from music_id_tagger.engine import Options, Stats, _one
from music_id_tagger.net import USER_AGENT
from music_id_tagger.websearch import beatport_ids
from tests.silence_bytes import SILENCE


def _file(tmp_path: Path) -> Path:
    path = tmp_path / "FISHER - Losing It.mp3"
    path.write_bytes(SILENCE["silence.mp3"])
    return path


class _Beatport:
    def __init__(self, calls: list[str]) -> None:
        self.calls = calls

    def search(self, *args, **kwargs):
        self.calls.append("beatport")
        return None

    def by_isrc(self, *args, **kwargs):
        self.calls.append("beatport")
        return None

    def by_id(self, *args, **kwargs):
        self.calls.append("beatport")
        return None


class _Spotify:
    def __init__(self, calls: list[str]) -> None:
        self.calls = calls

    def search(self, *args, **kwargs):
        self.calls.append("spotify")
        return None


def _options(**overrides) -> Options:
    values = {
        "use_shazam": True,
        "use_beatport": True,
        "use_spotify": True,
        "use_open_catalogs": True,
        "use_deezer": True,
        "use_apple": True,
        "use_musicbrainz": True,
        "use_discogs": True,
        "use_websearch": True,
        "dry_run": True,
        "acoustid_key": "",
    }
    values.update(overrides)
    return Options(**values)


def _run(path: Path, options: Options, calls: list[str], monkeypatch) -> None:
    async def recognize(*args, **kwargs):
        calls.append("shazam")
        return None

    def spy(name):
        def inner(*args, **kwargs):
            calls.append(name)
            return [] if name == "websearch" else None

        return inner

    monkeypatch.setattr("music_id_tagger.identify.recognize_shazam", recognize)
    monkeypatch.setattr("music_id_tagger.catalogs.deezer_search", spy("deezer"))
    monkeypatch.setattr("music_id_tagger.catalogs.deezer_by_isrc", spy("deezer"))
    monkeypatch.setattr("music_id_tagger.catalogs.itunes_search", spy("apple"))
    monkeypatch.setattr("music_id_tagger.catalogs.musicbrainz_search", spy("musicbrainz"))
    monkeypatch.setattr("music_id_tagger.catalogs.musicbrainz_by_isrc", spy("musicbrainz"))
    monkeypatch.setattr("music_id_tagger.catalogs.discogs_search", spy("discogs"))
    monkeypatch.setattr("music_id_tagger.websearch.beatport_ids", spy("websearch"))
    asyncio.run(
        _one(path, options, _Beatport(calls), _Spotify(calls), object(), lambda *_: None, Stats(), None)
    )


def test_websearch_off_does_not_call_network(tmp_path, monkeypatch):
    def boom(*args, **kwargs):
        raise AssertionError("session_get")

    monkeypatch.setattr("music_id_tagger.net.session_get", boom)

    async def recognize(*args, **kwargs):
        return None

    monkeypatch.setattr("music_id_tagger.identify.recognize_shazam", recognize)
    for name in ("deezer_search", "deezer_by_isrc", "itunes_search", "musicbrainz_search", "musicbrainz_by_isrc", "discogs_search"):
        monkeypatch.setattr(f"music_id_tagger.catalogs.{name}", lambda *args, **kwargs: None)
    asyncio.run(
        _one(
            _file(tmp_path),
            _options(use_websearch=False, use_shazam=False, use_spotify=False, use_open_catalogs=False),
            _Beatport([]),
            _Spotify([]),
            object(),
            lambda *_: None,
            Stats(),
            None,
        )
    )


@pytest.mark.parametrize(
    "flag",
    ["shazam", "beatport", "spotify", "deezer", "apple", "musicbrainz", "discogs", "websearch"],
)
def test_disabled_provider_is_not_called(tmp_path, monkeypatch, flag):
    calls: list[str] = []
    options = _options(**{f"use_{flag}": False})
    _run(_file(tmp_path), options, calls, monkeypatch)
    assert flag not in calls


def test_all_providers_off_make_no_calls(tmp_path, monkeypatch):
    def boom(*args, **kwargs):
        raise AssertionError("session_get")

    monkeypatch.setattr("music_id_tagger.net.session_get", boom)
    calls: list[str] = []
    options = _options(
        use_shazam=False,
        use_beatport=False,
        use_spotify=False,
        use_open_catalogs=False,
        use_deezer=False,
        use_apple=False,
        use_musicbrainz=False,
        use_discogs=False,
        use_websearch=False,
    )
    _run(_file(tmp_path), options, calls, monkeypatch)
    assert calls == []


def test_websearch_uses_product_user_agent(monkeypatch):
    seen = {}

    class Response:
        status_code = 200
        text = ""

    def fake(session, url, **kwargs):
        seen["headers"] = kwargs.get("headers") or {}
        return Response()

    monkeypatch.setattr("music_id_tagger.net.session_get", fake)
    assert beatport_ids("Marie Vaunt", "Rave Generator") == []
    assert seen["headers"]["User-Agent"] == USER_AGENT
    assert "Mozilla" not in seen["headers"]["User-Agent"]
