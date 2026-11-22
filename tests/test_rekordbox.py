import xml.etree.ElementTree as ET
from pathlib import Path

from music_id_tagger.rekordbox import apply_track, location_to_path, update_library


def test_location_decodes_windows_file_url():
    path = location_to_path("file://localhost/C:/Users/Rob%20Cortez/track.mp3")
    assert path == Path("C:/Users/Rob Cortez/track.mp3")


def test_apply_track_keeps_existing_title_and_writes_empty_fields():
    track = ET.fromstring(
        '<TRACK Name="Keep" Artist="Keep" Album="" Genre="" Year="" Label="" '
        'AverageBpm="0.00" Tonality=""><TEMPO Inizio="0.240" Bpm="0.00" Metro="4/4" Battito="1"/></TRACK>'
    )
    changes = apply_track(
        track,
        {"title": "New", "artist": "New", "genre": "Techno (Peak Time / Driving)", "bpm": 135, "key": "6A", "year": "2026", "label": "Second State"},
        keep_identity=True,
    )
    assert track.get("Name") == "Keep"
    assert track.get("Artist") == "Keep"
    assert track.get("Genre") == "Techno (Peak Time / Driving)"
    assert track.get("AverageBpm") == "135.00"
    assert track.get("Tonality") == "Gm"
    assert track.get("Year") == "2026"
    assert track.get("Label") == "Second State"
    assert track.find("TEMPO").get("Inizio") == "0.240"
    assert track.find("TEMPO").get("Bpm") == "135.00"
    assert any(line.startswith("Genre:") for line in changes)


def test_update_library_dry_run_does_not_touch_the_file(tmp_path: Path):
    xml = tmp_path / "library.xml"
    audio = tmp_path / "track.mp3"
    audio.write_bytes(b"0" * 40_000)
    location = "file://localhost/" + audio.resolve().as_posix().lstrip("/")
    xml.write_text(
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<DJ_PLAYLISTS Version="1.0.0"><COLLECTION Entries="1">'
        f'<TRACK Name="" Artist="" Genre="" AverageBpm="0.00" Tonality="" Location="{location}">'
        '<TEMPO Inizio="0.000" Bpm="0.00" Metro="4/4" Battito="1"/>'
        "</TRACK></COLLECTION><PLAYLISTS/></DJ_PLAYLISTS>",
        encoding="utf-8",
    )
    before = xml.read_bytes()
    changed, missing, notes = update_library(
        xml,
        {__import__("os").path.normcase(str(audio.resolve())): {"title": "It's the E", "artist": "Pan-Pot", "genre": "Techno", "bpm": 126, "key": "8A"}},
        keep_identity=True,
        dry_run=True,
    )
    assert changed == 1
    assert missing == 0
    assert notes and "It's the E" not in xml.read_text(encoding="utf-8")
    assert xml.read_bytes() == before
    assert not xml.with_suffix(".xml.bak").exists()


def test_update_library_writes_and_keeps_a_backup(tmp_path: Path):
    xml = tmp_path / "library.xml"
    audio = tmp_path / "track.mp3"
    audio.write_bytes(b"0" * 40_000)
    location = "file://localhost/" + audio.resolve().as_posix().lstrip("/")
    xml.write_text(
        "<DJ_PLAYLISTS><COLLECTION Entries=\"1\">"
        f'<TRACK Name="Old" Artist="" Genre="" Location="{location}" AverageBpm="0.00" Tonality="">'
        '<TEMPO Inizio="1.000" Bpm="0.00" Metro="4/4" Battito="1"/>'
        "</TRACK></COLLECTION><PLAYLISTS><NODE Name=\"ROOT\"/></PLAYLISTS></DJ_PLAYLISTS>",
        encoding="utf-8",
    )
    changed, missing, _notes = update_library(
        xml,
        {__import__("os").path.normcase(str(audio.resolve())): {"genre": "Techno (Raw / Deep / Hypnotic)", "bpm": 140, "key": "4A"}},
        keep_identity=True,
        dry_run=False,
    )
    text = xml.read_text(encoding="utf-8")
    assert changed == 1
    assert missing == 0
    assert "Techno (Raw / Deep / Hypnotic)" in text
    assert 'Name="Old"' in text
    assert 'Inizio="1.000"' in text
    assert "<PLAYLISTS>" in text
    assert xml.with_suffix(".xml.bak").is_file()
