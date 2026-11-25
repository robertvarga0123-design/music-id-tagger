from music_id_tagger.cli import _ARG_WARNING, resolve_secret


def test_secret_resolution_order(monkeypatch):
    asked: list[str] = []

    def ask(prompt: str) -> str:
        asked.append(prompt)
        return "from-prompt"

    value, warning = resolve_secret("from-arg", "MIT_BEATPORT_PASS", "Beatport jelszó: ", True, ask)
    assert value == "from-arg"
    assert warning == _ARG_WARNING
    assert "from-arg" not in warning
    assert asked == []

    monkeypatch.setenv("MIT_BEATPORT_PASS", "from-env")
    value, warning = resolve_secret("", "MIT_BEATPORT_PASS", "Beatport jelszó: ", True, ask)
    assert value == "from-env"
    assert warning is None
    assert asked == []

    monkeypatch.delenv("MIT_BEATPORT_PASS")
    value, warning = resolve_secret("", "MIT_SPOTIFY_SECRET", "Spotify Client Secret: ", True, ask)
    assert value == "from-prompt"
    assert warning is None
    assert asked == ["Spotify Client Secret: "]

    asked.clear()
    value, warning = resolve_secret("", "MIT_SPOTIFY_SECRET", "Spotify Client Secret: ", False, ask)
    assert value == ""
    assert warning is None
    assert asked == []
