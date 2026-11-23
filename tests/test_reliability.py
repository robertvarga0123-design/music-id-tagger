from music_id_tagger.catalogs import meta_from_deezer, meta_from_discogs, meta_from_itunes, meta_from_musicbrainz
from music_id_tagger.engine import apply_meta
from music_id_tagger.reconcile import bpm_half_time, durations_compatible, merge_hit


def test_deezer_track_exposes_bpm_and_isrc():
    meta = meta_from_deezer(
        {
            "id": 1,
            "title": "Losing It (Original Mix)",
            "title_short": "Losing It",
            "title_version": "Original Mix",
            "isrc": "ca5kr1821202",
            "bpm": 124.91,
            "duration": 248,
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
    assert meta["duration"] == 248
    assert meta["source"] == "deezer"
    assert meta_from_deezer({"error": {"type": "DataException"}}) is None


def test_itunes_ignores_broad_genre():
    meta = meta_from_itunes(
        {
            "trackName": "Losing It",
            "artistName": "FISHER",
            "collectionName": "Losing It - Single",
            "releaseDate": "2018-07-13T12:00:00Z",
            "trackTimeMillis": 248036,
            "primaryGenreName": "Dance",
            "trackViewUrl": "https://music.apple.com/us/album/losing-it/1?i=2",
        }
    )
    assert meta["album"] == "Losing It - Single"
    assert meta["year"] == "2018"
    assert 247 < meta["duration"] < 249
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
            "length": 248000,
        },
        exact=True,
    )
    assert meta["match_score"] == 100
    assert meta["mbid"] == "abc"
    assert meta["year"] == "2018"
    assert meta["duration"] == 248
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


def test_different_length_is_not_the_same_mix():
    assert durations_compatible(248, 251) is True
    assert durations_compatible(248, 401) is False
    assert durations_compatible(None, 248) is None
    found = {"title": "Losing It", "artist": "FISHER", "source": "shazam", "bpm": "125"}
    status = merge_hit(
        found,
        {
            "title": "Losing It",
            "artist": "FISHER",
            "bpm": 124,
            "duration": 401,
            "album": "Extended",
            "source": "deezer",
            "match_score": 100,
        },
        "FISHER",
        "Losing It",
        audio=True,
        file_duration=248,
    )
    assert status == "duration"
    assert found["bpm"] == "125"
    assert "album" not in found
    close = {"title": "Losing It", "artist": "FISHER", "source": "shazam"}
    assert (
        merge_hit(
            close,
            {"title": "Losing It", "artist": "FISHER", "duration": 251, "album": "Losing It", "source": "deezer", "match_score": 18},
            "FISHER",
            "Losing It",
            audio=True,
            file_duration=248,
        )
        == "accepted"
    )
    assert close["album"] == "Losing It"
    assert close["duration"] == 251


def test_different_cover_is_rejected_and_a_missing_cover_is_not():
    from music_id_tagger.covers import cover_hash, hashes_differ

    same = _png((8, 8, 48, 60))
    other = _png((36, 20, 76, 74))
    left = cover_hash(same)
    right = cover_hash(other)
    assert left and right
    assert hashes_differ(left, left) is False
    assert hashes_differ(left, right) is True
    found = {"title": "Losing It", "artist": "FISHER", "source": "shazam", "bpm": "125"}
    status = merge_hit(
        found,
        {
            "title": "Losing It",
            "artist": "FISHER",
            "album": "Wrong",
            "source": "deezer",
            "match_score": 20,
            "cover_hash": right,
        },
        "FISHER",
        "Losing It",
        audio=True,
        file_cover_hash=left,
    )
    assert status == "cover"
    assert "album" not in found
    assert found["bpm"] == "125"
    kept = {"title": "Losing It", "artist": "FISHER", "source": "shazam"}
    assert (
        merge_hit(
            kept,
            {"title": "Losing It", "artist": "FISHER", "album": "Losing It", "source": "deezer", "match_score": 18, "cover_hash": left},
            "FISHER",
            "Losing It",
            audio=True,
            file_cover_hash=left,
        )
        == "accepted"
    )
    assert kept["album"] == "Losing It"


def test_discogs_picks_the_mix_that_matches_the_file_length():
    release = {
        "id": 13500360,
        "title": "Losing It",
        "year": "2018",
        "artists": [{"name": "Fisher (16)"}],
        "labels": [{"name": "Catch & Release", "catno": "CR001"}],
        "images": [{"uri": "https://i.discogs.com/cover.jpg"}],
        "tracklist": [
            {"title": "Losing It (Original Mix)", "duration": "4:08"},
            {"title": "Losing It (Extended Mix)", "duration": "6:41"},
        ],
    }
    extended = meta_from_discogs(release, "FISHER", "Losing It", 401)
    original = meta_from_discogs(release, "FISHER", "Losing It", 248)
    assert extended["mix"] == "Extended Mix"
    assert original["mix"] == "Original Mix"
    assert extended["label"] == "Catch & Release"
    assert extended["catalog"] == "CR001"
    assert extended["artist"] == "Fisher"
    assert extended["source_url"] == "https://www.discogs.com/release/13500360"
    assert "genre" not in extended
    assert meta_from_discogs(release, "FISHER", "Losing It", 90) is None


def test_open_key_becomes_camelot_and_does_not_replace_a_beatport_key():
    filled = apply_meta({}, {"key": "1m", "source": "deezer"}, keep_identity=True)
    assert filled["key"] == "8A"
    assert filled["key_name"] == "Am"
    kept = apply_meta({"key": "9B"}, {"key": "Amin", "source": "deezer"}, keep_identity=True)
    assert kept["key"] == "9B"


def _png(box: tuple[int, int, int, int]) -> bytes:
    import io

    from PIL import Image, ImageDraw

    image = Image.new("RGB", (80, 80), (18, 18, 16))
    draw = ImageDraw.Draw(image)
    draw.rectangle(box, fill=(224, 168, 74))
    draw.ellipse((box[0], box[1], box[0] + 18, box[1] + 12), fill=(212, 101, 74))
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    return buf.getvalue()

