from music_id_tagger.catalogs import meta_from_deezer, meta_from_itunes, meta_from_musicbrainz
from music_id_tagger.engine import apply_meta
from music_id_tagger.reconcile import bpm_half_time, merge_hit


def test_deezer_track_exposes_bpm_and_isrc():
    meta = meta_from_deezer(
        {
            "id": 1,
            "title": "Losing It (Original Mix)",
            "title_short": "Losing It",
            "title_version": "Original Mix",
            "isrc": "ca5kr1821202",
            "bpm": 124.91,
            "release_date": "2018-07-13",
            "link": "https://www.deezer.com/track/1",
            "artist": {"name": "FISHER"},
            "album": {"title": "Losing It", "cover_xl": "https://cdn.example/cover.jpg"},
        }
    )
    assert meta["title"] == "Losing It"
    assert meta["mix"] == "Original Mix"
    assert meta["bpm"] == 124.91
    assert meta["isrc"] == "CA5KR1821202"
    assert meta["year"] == "2018"
    assert meta["source"] == "deezer"
    assert meta_from_deezer({"error": {"type": "DataException"}}) is None


def test_itunes_ignores_broad_genre():
    meta = meta_from_itunes(
        {
            "trackName": "Losing It",
            "artistName": "FISHER",
            "collectionName": "Losing It - Single",
            "releaseDate": "2018-07-13T12:00:00Z",
            "primaryGenreName": "Dance",
            "trackViewUrl": "https://music.apple.com/us/album/losing-it/1?i=2",
        }
    )
    assert meta["album"] == "Losing It - Single"
    assert meta["year"] == "2018"
    assert "genre" not in meta
    assert meta["source_url"].startswith("https://music.apple.com/")


def test_musicbrainz_isrc_recording():
    meta = meta_from_musicbrainz(
        {
            "id": "abc",
            "title": "Losing It",
            "artist-credit": [{"name": "FISHER", "artist": {"name": "FISHER"}}],
            "releases": [{"title": "Losing It", "date": "2018-07-13"}],
            "isrcs": ["CA5KR1821202"],
        },
        exact=True,
    )
    assert meta["match_score"] == 100
    assert meta["mbid"] == "abc"
    assert meta["year"] == "2018"
    assert meta["source_url"] == "https://musicbrainz.org/recording/abc"


def test_weak_hit_does_not_touch_bpm():
    found = {"title": "Losing It", "artist": "FISHER", "bpm": "128", "source": "shazam"}
    status = merge_hit(
        found,
        {"title": "Losing It", "artist": "FISHER", "bpm": 140, "source": "deezer", "match_score": 8},
        "FISHER",
        "Losing It",
        audio=True,
    )
    assert status == "weak"
    assert found["bpm"] == "128"
    assert "deezer" not in found["source"]


def test_deezer_fills_empty_bpm_but_does_not_replace_it():
    found = {"title": "Losing It", "artist": "FISHER", "source": "shazam"}
    assert (
        merge_hit(
            found,
            {"title": "Losing It", "artist": "FISHER", "bpm": 124.91, "album": "Losing It", "source": "deezer", "match_score": 15},
            "FISHER",
            "Losing It",
            audio=True,
        )
        == "accepted"
    )
    assert found["bpm"] == 124.91
    assert found["album"] == "Losing It"
    filled = dict(found)
    merge_hit(
        filled,
        {"title": "Losing It", "artist": "FISHER", "bpm": 99, "source": "deezer", "match_score": 15},
        "FISHER",
        "Losing It",
        audio=True,
    )
    assert filled["bpm"] == 124.91


def test_filename_only_needs_a_clearer_score_for_bpm():
    found = {"source": ""}
    status = merge_hit(
        found,
        {
            "title": "Losing It",
            "artist": "FISHER",
            "bpm": 125,
            "genre": "Tech House",
            "source": "beatport",
            "match_score": 13,
        },
        "FISHER",
        "Losing It",
        audio=False,
    )
    assert status == "accepted"
    assert "bpm" not in found
    assert "genre" not in found


def test_beatport_replaces_genre_and_refuses_half_time():
    found = {"title": "Losing It", "artist": "FISHER", "genre": "House", "bpm": 70, "source": "shazam"}
    merge_hit(
        found,
        {
            "title": "Losing It",
            "artist": "FISHER",
            "genre": "Tech House",
            "bpm": 140,
            "key": "9B",
            "source": "beatport",
            "match_score": 18,
            "beatport_id": 5,
        },
        "FISHER",
        "Losing It",
        audio=True,
    )
    assert found["genre"] == "Tech House"
    assert found["bpm"] == 70
    assert found["key"] == "9B"
    assert bpm_half_time(70, 140) is True
    assert bpm_half_time(128, 130) is False


def test_apply_meta_keeps_file_bpm_against_half_time_and_non_beatport():
    kept = apply_meta(
        {"bpm": "140", "genre": "Techno (Peak Time / Driving)", "isrc": "AAA"},
        {"bpm": "70", "genre": "Dance", "isrc": "BBB", "source": "deezer"},
        keep_identity=True,
    )
    assert kept["bpm"] == "140"
    assert kept["genre"] == "Techno (Peak Time / Driving)"
    assert kept["isrc"] == "AAA"
    filled = apply_meta({"title": "X"}, {"bpm": "124.91", "album": "EP", "source": "deezer"}, keep_identity=True)
    assert filled["bpm"] == "124.91"
    replaced = apply_meta({"bpm": "120", "genre": "House"}, {"bpm": "128", "genre": "Techno", "source": "beatport"}, keep_identity=True)
    assert replaced["bpm"] == "128"
    assert replaced["genre"] == "Techno"


def test_different_recording_is_rejected():
    found = {"title": "Losing It", "artist": "FISHER", "source": "shazam", "bpm": "125"}
    status = merge_hit(
        found,
        {"title": "Losing Control", "artist": "Someone Else", "bpm": 100, "source": "apple", "match_score": 20},
        "FISHER",
        "Losing It",
        audio=True,
    )
    assert status == "rejected"
    assert found["bpm"] == "125"
