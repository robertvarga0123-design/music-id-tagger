from music_id_tagger.config import save_settings


def test_password_is_not_written_as_plain_text(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    save_settings(
        {
            "beatport_user": "DUDEHUN",
            "beatport_password": "secret-value",
            "spotify_client_secret": "spotify-secret",
        }
    )
    text = (tmp_path / "MusicIDTagger" / "settings.json").read_text(encoding="utf-8")
    assert "DUDEHUN" in text
    assert "secret-value" not in text
    assert "spotify-secret" not in text
