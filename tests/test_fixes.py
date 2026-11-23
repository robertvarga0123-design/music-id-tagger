import xml.etree.ElementTree as ET
from pathlib import Path

from music_id_tagger.engine import apply_meta
from music_id_tagger.match import artists_compatible, titles_compatible
from music_id_tagger.rekordbox import apply_track
from music_id_tagger.tags import COMMENT_MARKER, ID3_V2_VERSION, merge_comment, parse_bpm, snapshot_tags, write_tags
from music_id_tagger.undo import begin_run, commit_run, revert
from tests.silence_bytes import SILENCE


def _copy(name: str, dest: Path) -> Path:
    target = dest / name
    target.write_bytes(SILENCE[name])
    return target


def test_parse_bpm_accepts_decimals_and_commas():
    assert parse_bpm("128.5") == 129
    assert parse_bpm("128,00") == 128
    assert parse_bpm("128.4") == 128
    assert parse_bpm(135) == 135
    assert parse_bpm("nem bpm") is None
    assert parse_bpm("nan") is None
    assert parse_bpm("") is None


def test_decimal_bpm_round_trip(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path / "app"))
    path = _copy("silence.mp3", tmp_path)
    write_tags(path, {"bpm": "128,5", "title": "Következő"}, dry_run=False, embed_cover=False)
    assert snapshot_tags(path)["bpm"] == "129"
    write_tags(path, {"bpm": snapshot_tags(path)["bpm"]}, dry_run=False, embed_cover=False)
    assert snapshot_tags(path)["bpm"] == "129"


def test_flac_comment_is_idempotent(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path / "app"))
    path = _copy("silence.flac", tmp_path)
    from mutagen.flac import FLAC

    audio = FLAC(path)
    audio["comment"] = "saját megjegyzés"
    audio.save()
    meta = {"beatport_id": "12345", "bpm": "126"}
    write_tags(path, meta, dry_run=False, embed_cover=False)
    write_tags(path, meta, dry_run=False, embed_cover=False)
    comment = FLAC(path)["comment"][0]
    assert comment.count(COMMENT_MARKER) == 1
    assert comment.startswith("saját megjegyzés")
    assert "Beatport ID: 12345" in comment


def test_mp4_comment_keeps_user_text(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path / "app"))
    path = _copy("silence.m4a", tmp_path)
    from mutagen.mp4 import MP4

    audio = MP4(path)
    audio["\xa9cmt"] = ["saját megjegyzés"]
    audio.save()
    meta = {"beatport_id": "99", "title": "Cím"}
    write_tags(path, meta, dry_run=False, embed_cover=False)
    write_tags(path, meta, dry_run=False, embed_cover=False)
    comment = MP4(path)["\xa9cmt"][0]
    assert comment.count(COMMENT_MARKER) == 1
    assert "saját megjegyzés" in comment
    assert merge_comment(comment, "Beatport ID: 99").count(COMMENT_MARKER) == 1


def test_shazam_genre_does_not_replace_existing():
    kept = apply_meta(
        {"genre": "Techno (Peak Time / Driving)", "title": "Régi"},
        {"genre": "Electronic", "title": "Új", "source": "shazam"},
        keep_identity=True,
    )
    assert kept["genre"] == "Techno (Peak Time / Driving)"
    assert kept["title"] == "Régi"
    filled = apply_meta({"genre": ""}, {"genre": "Electronic", "source": "shazam"}, keep_identity=True)
    assert filled["genre"] == "Electronic"
    replaced = apply_meta(
        {"genre": "House"},
        {"genre": "Techno (Raw / Deep / Hypnotic)", "source": "shazam+beatport"},
        keep_identity=True,
    )
    assert replaced["genre"] == "Techno (Raw / Deep / Hypnotic)"


def test_mp3_id3_is_written_as_v23(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path / "app"))
    path = _copy("silence.mp3", tmp_path)
    write_tags(path, {"title": "V23", "artist": "Teszt"}, dry_run=False, embed_cover=False)
    from mutagen.id3 import ID3

    assert ID3(path).version == (2, ID3_V2_VERSION, 0)


def test_rekordbox_bpm_threshold_and_single_tempo():
    one = ET.fromstring(
        '<TRACK AverageBpm="120.00" Tonality=""><TEMPO Inizio="0.5" Bpm="120.00" Metro="4/4" Battito="1"/></TRACK>'
    )
    apply_track(one, {"bpm": 128}, keep_identity=True)
    assert one.get("AverageBpm") == "128.00"
    assert one.find("TEMPO").get("Bpm") == "128.00"
    assert one.find("TEMPO").get("Inizio") == "0.5"

    close = ET.fromstring('<TRACK AverageBpm="135.00"><TEMPO Bpm="135.00"/></TRACK>')
    changes = apply_track(close, {"bpm": 135.4}, keep_identity=True)
    assert close.get("AverageBpm") == "135.00"
    assert close.find("TEMPO").get("Bpm") == "135.00"
    assert not any(line.startswith("AverageBpm") for line in changes)

    edge = ET.fromstring('<TRACK AverageBpm="120.00"><TEMPO Bpm="120.00"/></TRACK>')
    apply_track(edge, {"bpm": 121}, keep_identity=True)
    assert edge.get("AverageBpm") == "120.00"
    assert edge.find("TEMPO").get("Bpm") == "120.00"

    many = ET.fromstring(
        '<TRACK AverageBpm="100.00"><TEMPO Bpm="100.00"/><TEMPO Bpm="110.00"/></TRACK>'
    )
    apply_track(many, {"bpm": 140}, keep_identity=True)
    assert many.get("AverageBpm") == "140.00"
    assert [item.get("Bpm") for item in many.findall("TEMPO")] == ["100.00", "110.00"]

    frozen = ET.fromstring('<TRACK AverageBpm="100.00"><TEMPO Bpm="100.00"/></TRACK>')
    apply_track(frozen, {"bpm": 140}, keep_identity=True, write_bpm=False)
    assert frozen.get("AverageBpm") == "100.00"
    assert frozen.find("TEMPO").get("Bpm") == "100.00"


def test_artist_and_short_title_are_strict():
    assert artists_compatible("DJ A", "DJ B") is False
    assert artists_compatible("DJ Alpha", "Alpha") is True
    assert titles_compatible("Go", "Let It Go") is False
    assert titles_compatible("Go", "Go") is True
    assert titles_compatible("Losing It", "Losing It", "Extended Mix") is True
    assert artists_compatible("The DJ", "DJ MC") is False


def test_undo_restores_original_tags(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path / "app"))
    path = _copy("silence.mp3", tmp_path)
    from mutagen.easyid3 import EasyID3
    from mutagen.mp3 import MP3

    audio = MP3(path, ID3=EasyID3)
    if audio.tags is None:
        audio.add_tags()
    audio["title"] = "Régi cím"
    audio["artist"] = "Régi előadó"
    audio.save()
    from mutagen.id3 import COMM, ID3

    tagged = ID3(path)
    tagged.add(COMM(encoding=3, lang="eng", desc="", text="saját megjegyzés"))
    tagged.save(v2_version=3)
    begin_run()
    write_tags(
        path,
        {"title": "Új cím", "artist": "Új előadó", "genre": "Techno", "bpm": "128.5", "beatport_id": "55"},
        dry_run=False,
        embed_cover=False,
    )
    run_file = commit_run()
    assert run_file is not None
    assert snapshot_tags(path)["title"] == "Új cím"
    assert snapshot_tags(path)["bpm"] == "129"
    assert COMMENT_MARKER not in snapshot_tags(path)["comment"] or "Beatport" in snapshot_tags(path)["comment"]
    assert "saját megjegyzés" in snapshot_tags(path)["comment"]
    text = run_file.read_text(encoding="utf-8")
    assert "secret" not in text
    notes: list[str] = []
    restored = revert(run_file, lambda _level, message: notes.append(message))
    assert restored == 1
    assert snapshot_tags(path)["title"] == "Régi cím"
    assert snapshot_tags(path)["artist"] == "Régi előadó"
    assert snapshot_tags(path)["comment"] == "saját megjegyzés"
    assert "Beatport" not in snapshot_tags(path)["comment"]
    import json

    payload = json.loads(run_file.read_text(encoding="utf-8"))
    payload[0]["mtime_ns"] = 1
    run_file.write_text(json.dumps(payload), encoding="utf-8")
    skipped = revert(run_file, lambda _level, message: notes.append(message), confirm=lambda _path: False)
    assert skipped == 0
    assert snapshot_tags(path)["title"] == "Régi cím"


def test_wav_id3_is_v23_and_bpm_rounds(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path / "app"))
    path = tmp_path / "silence.wav"
    import wave

    with wave.open(str(path), "w") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(8000)
        handle.writeframes(b"\x00\x00" * 800)
    write_tags(path, {"title": "Hullám", "bpm": "128.5"}, dry_run=False, embed_cover=False)
    from mutagen.wave import WAVE

    audio = WAVE(path)
    assert audio.tags is not None
    assert audio.tags.version == (2, 3, 0)
    assert snapshot_tags(path)["bpm"] == "129"
    assert snapshot_tags(path)["title"] == "Hullám"


def test_dry_run_writes_no_undo(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path / "app"))
    path = _copy("silence.mp3", tmp_path)
    from music_id_tagger.engine import Options
    from music_id_tagger.undo import list_runs

    assert Options().write_bpm_to_xml is True
    before = snapshot_tags(path)["title"]
    write_tags(path, {"title": "Nem íródik"}, dry_run=True, embed_cover=False)
    assert list_runs() == []
    assert snapshot_tags(path)["title"] == before
