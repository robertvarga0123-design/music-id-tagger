from music_id_tagger.config import save_settings


def test_password_is_not_written_as_plain_text(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    save_settings(
        {
            "beatport_user": "testuser",
            "beatport_password": "secret-value",
            "spotify_client_secret": "spotify-secret",
            "grok_key": "grok-secret-value",
            "gemini_key": "gemini-secret-value",
        }
    )
    text = (tmp_path / "MusicIDTagger" / "settings.json").read_text(encoding="utf-8")
    assert "testuser" in text
    assert "secret-value" not in text
    assert "spotify-secret" not in text
    assert "grok-secret-value" not in text
    assert "gemini-secret-value" not in text


def test_empty_secret_does_not_erase_the_saved_blob(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    folder = tmp_path / "MusicIDTagger"
    folder.mkdir()
    (folder / "settings.json").write_text(
        '{"spotify_client_id": "abc", "spotify_client_secret_dpapi": "kept-blob", "beatport_password_dpapi": "kept-pass", "grok_key_dpapi": "kept-grok", "gemini_key_dpapi": "kept-gemini"}',
        encoding="utf-8",
    )
    save_settings(
        {
            "spotify_client_id": "abc",
            "spotify_client_secret": "",
            "beatport_password": "",
            "grok_key": "",
            "gemini_key": "",
        }
    )
    text = (folder / "settings.json").read_text(encoding="utf-8")
    assert "kept-blob" in text
    assert "kept-pass" in text
    assert "kept-grok" in text
    assert "kept-gemini" in text
    assert "abc" in text
