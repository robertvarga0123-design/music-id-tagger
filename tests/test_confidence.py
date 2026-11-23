from music_id_tagger.beatport import beatport_track_url
from music_id_tagger.identify import _shazam_url
from music_id_tagger.match import is_uncertain
from music_id_tagger.spotify import _spotify_url


def test_filename_guess_without_audio_match_is_uncertain():
    assert is_uncertain({"source": "beatport", "match_score": 20}, guessed=True) is True


def test_shazam_plus_strong_beatport_score_is_sure():
    assert is_uncertain({"source": "shazam+beatport", "match_score": 16}, guessed=False) is False


def test_weak_catalog_score_is_uncertain():
    assert is_uncertain({"source": "shazam+beatport", "match_score": 6}, guessed=False) is True


def test_shazam_without_a_catalog_is_uncertain():
    assert is_uncertain({"source": "shazam"}, guessed=False) is True
    assert is_uncertain({"source": "shazam+deezer", "match_score": 18}, guessed=False) is True
    assert is_uncertain({}, guessed=False) is True


def test_parse_beatport_id_from_track_link():
    from music_id_tagger.beatport import parse_beatport_id

    assert parse_beatport_id("https://www.beatport.com/track/its-the-e/12345678") == "12345678"
    assert parse_beatport_id("https://www.beatport.com/hu/track/its-the-e/99?s=1") == "99"
    assert parse_beatport_id("12345678") == "12345678"
    assert parse_beatport_id("nem link") is None
    assert beatport_track_url({"slug": "its-the-e", "id": 123}) == "https://www.beatport.com/track/its-the-e/123"
    assert _spotify_url({"id": "abc"}) == "https://open.spotify.com/track/abc"
    assert _shazam_url({"url": "https://www.shazam.com/track/1/its-the-e"}) == "https://www.shazam.com/track/1/its-the-e"
    assert _shazam_url({"url": "http://evil.example"}) is None
