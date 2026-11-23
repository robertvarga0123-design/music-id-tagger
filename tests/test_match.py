import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from music_id_tagger.beatport import normalize_track
from music_id_tagger.match import (
    beatport_genre,
    best_track,
    camelot_or_name,
    parse_filename,
    score_track,
    to_camelot,
)


def test_genre_label():
    assert beatport_genre("Techno", "Peak Time / Driving") == "Techno (Peak Time / Driving)"
    assert beatport_genre("Techno (Peak Time / Driving)", None) == "Techno (Peak Time / Driving)"
    assert beatport_genre("Trance (Main Floor)", "Tech Trance") == "Trance (Main Floor)"
    assert beatport_genre("Techno (Raw / Deep / Hypnotic)", "Raw") == "Techno (Raw / Deep / Hypnotic)"
    assert beatport_genre("", "Deep House") == "Deep House"
    assert beatport_genre(None, None) is None


def test_camelot():
    assert camelot_or_name({"camelot_number": 8, "camelot_letter": "A", "name": "A Minor"}) == "8A"
    assert camelot_or_name({"name": "F# Minor"}) == "F# Minor"
    assert camelot_or_name({"camelot": "8A", "name": "A min"}) == "8A"
    assert to_camelot("8A") == "8A"
    assert to_camelot("1m") == "8A"
    assert to_camelot("1d") == "8B"
    assert to_camelot("12d") == "7B"
    assert to_camelot("Amin") == "8A"
    assert to_camelot("G#min") == "1A"
    assert to_camelot("F# Minor") == "11A"
    assert to_camelot("not a key") is None
    assert camelot_or_name("1m") == "8A"


def test_score_prefers_real_match():
    tracks = [
        {"name": "Something Else", "mix_name": "Original Mix", "artists": [{"name": "Other"}]},
        {"name": "Losing It", "mix_name": "Extended Mix", "artists": [{"name": "Fisher"}]},
    ]
    winner, score = best_track(tracks, "Fisher", "Losing It")
    assert winner["name"] == "Losing It"
    assert score >= 5
    weak, weak_score = best_track(tracks, "Nobody", "Unrelated Title")
    assert weak is None
    assert weak_score < 5
    assert score_track(tracks[1], "Fisher", "Losing It") > score_track(tracks[0], "Fisher", "Losing It")


def test_filename():
    assert parse_filename("01 Fisher - Losing It (Extended Mix).mp3") == (
        "Fisher",
        "Losing It (Extended Mix)",
    )
    assert parse_filename("Artist_Name - Track_Title.flac") == ("Artist Name", "Track Title")
    assert parse_filename("nosplit.mp3") is None


def test_normalize_uses_track_fields():
    meta = normalize_track(
        {
            "id": 10766349,
            "name": "Losing It",
            "mix_name": "Extended",
            "artists": [{"name": "FISHER (OZ)"}],
            "bpm": 125,
            "isrc": "CA5KR1821203",
            "catalog_number": "CR001B",
            "publish_date": "2018-07-13",
            "length_ms": 248000,
            "genre": {"name": "Tech House"},
            "sub_genre": None,
            "key": {"camelot_number": 9, "camelot_letter": "B", "name": "G Major"},
            "release": {"name": "Losing It", "label": {"name": "Catch & Release"}},
        }
    )
    assert meta["year"] == "2018"
    assert meta["catalog"] == "CR001B"
    assert meta["isrc"] == "CA5KR1821203"
    assert meta["key"] == "9B"
    assert meta["duration"] == 248
    assert meta["genre"] == "Tech House"
    assert meta["label"] == "Catch & Release"


def test_rejects_same_artist_different_title():
    weekend = {
        "name": "Weekend",
        "mix_name": "Original Mix",
        "artists": [
            {"name": "Pablo Say"},
            {"name": "David LeSal"},
            {"name": "Viv Castle"},
        ],
    }
    right = {
        "name": "It's the E",
        "mix_name": "Original Mix",
        "artists": [{"name": "Pan-Pot"}],
    }
    wrong_artist = {
        "name": "It's the E",
        "mix_name": "Original Mix",
        "artists": [{"name": "Dajusch"}],
    }
    assert score_track(weekend, "Pablo Say, David LeSal, Viv Castle", "It's the E") < 5
    assert score_track(wrong_artist, "Pablo Say", "It's the E") < 5
    winner, score = best_track([weekend, wrong_artist, right], "Pan-Pot", "It's the E")
    assert winner["name"] == "It's the E"
    assert score >= 5
    assert best_track([weekend], "Pablo Say, David LeSal, Viv Castle", "It's the E")[0] is None


if __name__ == "__main__":
    test_genre_label()
    test_camelot()
    test_score_prefers_real_match()
    test_filename()
    test_normalize_uses_track_fields()
    test_rejects_same_artist_different_title()
    print("ok")
