import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from music_id_tagger.spotify import normalize_track, spotify_key


def test_camelot_from_spotify_pitch():
    assert spotify_key(7, 1) == ("9B", "G Major")
    assert spotify_key(9, 0) == ("8A", "Am")
    assert spotify_key(-1, 1) == (None, None)
    assert spotify_key(None, None) == (None, None)


def test_normalize_catalog_fields():
    meta = normalize_track(
        {
            "id": "4uLU6hMCjMI75M1A2tKUQC",
            "name": "Losing It",
            "artists": [{"name": "FISHER"}],
            "album": {
                "name": "Losing It",
                "release_date": "2018-07-13",
                "images": [
                    {"url": "https://i.scdn.co/image/small", "width": 64},
                    {"url": "https://i.scdn.co/image/large", "width": 640},
                ],
            },
            "external_ids": {"isrc": "CA5KR1821203"},
        }
    )
    assert meta["artist"] == "FISHER"
    assert meta["album"] == "Losing It"
    assert meta["year"] == "2018"
    assert meta["isrc"] == "CA5KR1821203"
    assert meta["cover_url"] == "https://i.scdn.co/image/large"
    assert meta["spotify_id"] == "4uLU6hMCjMI75M1A2tKUQC"
    assert "bpm" not in meta


def test_normalize_uses_features_when_present():
    meta = normalize_track(
        {"id": "abc", "name": "Losing It", "artists": [{"name": "FISHER"}], "album": {}},
        {"tempo": 125.2, "key": 7, "mode": 1},
    )
    assert meta["bpm"] == 125
    assert meta["key"] == "9B"
    assert meta["key_name"] == "G Major"


if __name__ == "__main__":
    test_camelot_from_spotify_pitch()
    test_normalize_catalog_fields()
    test_normalize_uses_features_when_present()
    print("ok")
