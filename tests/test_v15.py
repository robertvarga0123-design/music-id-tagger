import asyncio
from pathlib import Path

from music_id_tagger.cache import cache_path, clear, lookup, store
from music_id_tagger.engine import Options, Stats, _one
from music_id_tagger.match import CAMELOT_TO_NAME, camelot_to_open, format_key, rank_tracks, to_camelot
from music_id_tagger.pending import (
    FIELDS,
    LogBook,
    Pending,
    apply_genre_map,
    apply_pending,
    choose_candidate,
    duplicate_groups,
    eta_text,
    export_csv,
    filter_pending,
    masked_after,
    needs_lookup,
    parse_genre_map,
    render_filename,
    select_for_apply,
    unique_target,
)
from music_id_tagger.rekordbox import path_to_location
from music_id_tagger.tags import read_tags, write_tags
from tests.silence_bytes import SILENCE

SILENCE_MP3 = Path(__file__).parent / "fixtures" / "silence.mp3"


def _audio(folder: Path, name: str = "track.mp3") -> Path:
    path = folder / name
    path.write_bytes(SILENCE_MP3.read_bytes() if SILENCE_MP3.is_file() else SILENCE["silence.mp3"])
    return path


def _hit(**extra) -> dict:
    data = {
        "title": "Losing It",
        "artist": "FISHER",
        "bpm": "125",
        "key": "8A",
        "genre": "Tech House",
        "source": "beatport",
        "match_score": 20,
        "beatport_id": "99",
        "source_url": "https://www.beatport.com/track/losing-it/99",
    }
    data.update(extra)
    return data


class _Portal:
    def __init__(self, calls: list[str], hit: dict | None) -> None:
        self.calls = calls
        self.hit = hit

    def search(self, *args, **kwargs):
        self.calls.append("search")
        return self.hit

    def ranked(self, *args, **kwargs):
        self.calls.append("ranked")
        if not self.hit:
            return []
        second = dict(self.hit)
        second["mix"] = "Extended Mix"
        second["match_score"] = 12
        third = dict(self.hit)
        third["title"] = "Losing It (Dub)"
        third["match_score"] = 8
        return [self.hit, second, third]

    def by_isrc(self, *args, **kwargs):
        return None

    def by_id(self, *args, **kwargs):
        return None


def _options(**overrides) -> Options:
    values = {
        "use_shazam": False,
        "use_beatport": True,
        "use_spotify": False,
        "use_open_catalogs": False,
        "use_websearch": False,
        "dry_run": True,
        "defer_write": True,
        "acoustid_key": "",
    }
    values.update(overrides)
    return Options(**values)


def _run(path: Path, options: Options, portal) -> Stats:
    stats = Stats()
    asyncio.run(_one(path, options, portal, None, object(), lambda *_: None, stats, None))
    return stats


def test_twenty_four_keys_round_trip():
    assert len(CAMELOT_TO_NAME) == 24
    for code, name in CAMELOT_TO_NAME.items():
        opened = camelot_to_open(code)
        assert opened
        assert to_camelot(opened) == code
        assert format_key(code, "open") == opened
        assert format_key(opened, "camelot") == code
        assert format_key(code, "traditional") == name
        assert to_camelot(name) == code
        assert format_key(name, "camelot") == code
        assert format_key(name, "open") == opened


def test_rank_tracks_keeps_three_and_catalog_order_on_ties():
    tracks = [
        {"name": "Losing It", "artists": [{"name": "FISHER"}]},
        {"name": "Losing It", "artists": [{"name": "FISHER"}]},
        {"name": "Other", "artists": [{"name": "FISHER"}]},
        {"name": "Losing It", "mix_name": "Extended", "artists": [{"name": "FISHER"}]},
    ]
    ranked = rank_tracks(tracks, "FISHER", "Losing It", limit=3)
    assert len(ranked) == 3
    assert ranked[0][1] >= ranked[1][1] >= ranked[2][1]


def test_genre_map_parse_and_apply():
    table = parse_genre_map("# megjegyzés\nTechno (Peak Time / Driving) -> Peak Techno\nHouse\tDeep House\n")
    assert table["Techno (Peak Time / Driving)"] == "Peak Techno"
    assert apply_genre_map("techno (peak time / driving)", table) == "Peak Techno"
    assert apply_genre_map("House", table) == "Deep House"
    assert apply_genre_map("Minimal", table) == "Minimal"


def test_field_mask_respects_toggles_fill_missing_and_key_style():
    item = Pending(
        path="a.mp3",
        name="a.mp3",
        status="ok",
        before={"bpm": "100", "key": "8A", "title": "Old", "artist": "Old"},
        after={"bpm": "128", "key": "9A", "title": "New", "artist": "New", "genre": "Techno (Peak Time / Driving)"},
    )
    masked = masked_after(
        item,
        {"bpm": False, "identity": False, "key": True, "genre": True},
        False,
        "open",
        {"Techno (Peak Time / Driving)": "Peak Techno"},
    )
    assert masked["bpm"] == "100"
    assert masked["title"] == "Old"
    assert masked["key"] == format_key("9A", "open")
    assert masked["genre"] == "Peak Techno"
    filled = masked_after(item, {}, True, "camelot", {})
    assert filled["bpm"] == "100"
    assert filled["title"] == "Old"
    assert filled["genre"] == "Techno (Peak Time / Driving)"


def test_needs_lookup_when_a_requested_field_is_empty():
    tags = {key: "x" for keys in FIELDS.values() for key in keys}
    assert needs_lookup(tags, {"cover": False}, has_cover=False) is False
    tags["album"] = ""
    assert needs_lookup(tags, {"cover": False}, has_cover=False) is True
    tags["album"] = "x"
    tags["key_name"] = ""
    assert needs_lookup(tags, {"cover": False}, has_cover=False) is False


def test_cache_does_not_create_a_database_on_lookup(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path / "cfg"))
    path = _audio(tmp_path)
    assert lookup(path) is None
    assert not cache_path().exists()
    store(path, {"found": {"title": "A"}, "status": "ok"}, "beatport", False)
    got = lookup(path)
    assert got["found"]["title"] == "A"
    assert got["source"] == "beatport"
    assert got["unsure"] is False
    path.write_bytes(path.read_bytes() + b"\x00")
    assert lookup(path) is None
    clear()
    assert not cache_path().exists()


def test_unchanged_file_skips_the_network_until_rescan(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path / "cfg"))
    path = _audio(tmp_path, "FISHER - Losing It.mp3")
    calls: list[str] = []
    portal = _Portal(calls, _hit())
    first = _run(path, _options(), portal)
    assert calls == ["ranked"]
    assert first.pending and first.pending[0].candidates
    assert len(first.pending[0].candidates) == 3
    same = path.read_bytes()
    second = _run(path, _options(), portal)
    assert calls == ["ranked"]
    assert second.pending[0].source
    assert path.read_bytes() == same
    third = _run(path, _options(rescan=True), portal)
    assert calls == ["ranked", "ranked"]
    assert third.ok == 1


def test_tag_first_calls_beatport_before_shazam_and_can_skip_it(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path / "cfg"))
    path = _audio(tmp_path)
    write_tags(path, {"artist": "FISHER", "title": "Losing It"}, False, False)
    order: list[str] = []

    class Portal(_Portal):
        def ranked(self, *args, **kwargs):
            order.append("beatport")
            return [self.hit] if self.hit else []

    async def recognize(*args, **kwargs):
        order.append("shazam")
        return None

    monkeypatch.setattr("music_id_tagger.identify.recognize_shazam", recognize)
    _run(path, _options(use_shazam=True, tag_first=True), Portal(order, _hit()))
    assert order == ["beatport"]

    missed = tmp_path / "second.mp3"
    missed.write_bytes(path.read_bytes())
    write_tags(missed, {"artist": "FISHER", "title": "Losing It"}, False, False)
    order.clear()
    _run(missed, _options(use_shazam=True, tag_first=True, rescan=True), Portal(order, None))
    assert order[0] == "beatport"
    assert "shazam" in order


def test_fill_missing_skips_network_for_a_complete_file(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path / "cfg"))
    path = _audio(tmp_path)
    write_tags(
        path,
        {
            "title": "Losing It",
            "artist": "FISHER",
            "album": "Album",
            "genre": "Tech House",
            "year": "2018",
            "bpm": "125",
            "key": "8A",
            "label": "Catch",
            "isrc": "USAAA1234567",
        },
        False,
        False,
    )

    def boom(*args, **kwargs):
        raise AssertionError("network")

    enabled = {name: name != "cover" for name in FIELDS}
    asyncio.run(
        _one(
            path,
            _options(use_shazam=True, fill_missing_only=True, enabled_fields=enabled),
            type("P", (), {"search": boom, "ranked": boom, "by_isrc": boom, "by_id": boom})(),
            None,
            object(),
            lambda *_: None,
            Stats(),
            None,
        )
    )


def test_apply_pending_does_not_search_again(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path / "cfg"))
    path = _audio(tmp_path)
    write_tags(path, {"title": "Old", "artist": "Old"}, False, False)
    item = Pending(
        path=str(path.resolve()),
        name=path.name,
        status="ok",
        before=read_tags(path),
        after={
            "title": "Old",
            "artist": "Old",
            "bpm": "128",
            "key": "8A",
            "genre": "Techno (Peak Time / Driving)",
        },
        source="beatport",
        confidence=90,
    )

    class Opt:
        enabled_fields: dict = {}
        fill_missing_only = False
        embed_cover = False
        rename_template = ""
        key_format = "open"
        genre_map = {"Techno (Peak Time / Driving)": "Peak Techno"}
        keep_identity = True
        write_bpm_to_xml = True

    written = apply_pending([item], Opt(), lambda *_: None)
    assert written == 1
    tags = read_tags(path)
    assert "128" in str(tags.get("bpm"))
    assert tags.get("key") == "1m"
    assert tags.get("genre") == "Peak Techno"
    assert item.status == "applied"


def test_rename_collision_is_undoable_and_updates_rekordbox_location(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path / "cfg"))
    first = _audio(tmp_path, "one.mp3")
    second = _audio(tmp_path, "two.mp3")
    xml = tmp_path / "library.xml"
    location = "file://localhost/" + first.resolve().as_posix().lstrip("/")
    xml.write_text(
        "<DJ_PLAYLISTS><COLLECTION Entries=\"1\">"
        f'<TRACK Name="Old" Artist="Old" Genre="" Location="{location}" AverageBpm="0.00" Tonality="">'
        '<TEMPO Inizio="0.000" Bpm="0.00" Metro="4/4" Battito="1"/>'
        "</TRACK></COLLECTION><PLAYLISTS/></DJ_PLAYLISTS>",
        encoding="utf-8",
    )

    def row(path: Path) -> Pending:
        return Pending(
            path=str(path.resolve()),
            name=path.name,
            status="ok",
            before={"artist": "Old", "title": "Old"},
            after={"artist": "Pan-Pot", "title": "Its the E", "bpm": "126", "key": "8A"},
            source="beatport",
        )

    class Opt:
        enabled_fields = {"identity": True, "bpm": True, "key": True}
        fill_missing_only = False
        embed_cover = False
        rename_template = "{artist} - {title}"
        key_format = "camelot"
        genre_map: dict = {}
        keep_identity = False
        write_bpm_to_xml = True

    apply_pending([row(first), row(second)], Opt(), lambda *_: None, [xml])
    names = sorted(item.name for item in tmp_path.glob("*.mp3"))
    assert "Pan-Pot - Its the E.mp3" in names
    assert "Pan-Pot - Its the E (2).mp3" in names
    text = xml.read_text(encoding="utf-8")
    assert "Pan-Pot - Its the E.mp3" in text
    assert "Pan-Pot - Its the E.mp3" in path_to_location(tmp_path / "Pan-Pot - Its the E.mp3")

    from music_id_tagger.undo import list_runs, revert

    runs = list_runs()
    assert runs
    revert(runs[0], lambda *_: None)
    assert first.is_file()
    assert second.is_file()
    assert not (tmp_path / "Pan-Pot - Its the E.mp3").exists()


def test_reports_candidates_and_filters():
    sure = Pending(
        path="/a.mp3",
        name="a.mp3",
        status="ok",
        before={"artist": "A", "title": "Old"},
        after={"artist": "A", "title": "New", "isrc": "ABC", "bpm": "120"},
        changed={"title": "New"},
        source="beatport",
        confidence=90,
        duration=100,
    )
    unsure = Pending(
        path="/b.mp3",
        name="b.mp3",
        status="unsure",
        before={"artist": "A", "title": "Old"},
        after={"artist": "A", "title": "Other", "isrc": "ABC", "bpm": "120"},
        source="beatport",
        confidence=40,
        unsure=True,
        duration=120,
        candidates=[{"title": "Picked", "artist": "A", "bpm": "130", "key": "8A", "genre": "Techno", "score": 11}],
    )
    missed = Pending(path="/c.mp3", name="c.mp3", status="missed", before={}, after={}, source="")
    assert [item.name for item in filter_pending([sure, unsure, missed], "unsure")] == ["b.mp3"]
    assert [item.name for item in filter_pending([sure, unsure, missed], "missed")] == ["c.mp3"]
    assert [item.name for item in select_for_apply([sure, unsure, missed], "sure")] == ["a.mp3"]
    assert [item.name for item in select_for_apply([sure, unsure, missed], "selected", ["/b.mp3"])] == ["b.mp3"]
    choose_candidate(unsure, 0)
    assert unsure.status == "ok"
    assert unsure.after["title"] == "Picked"
    assert unsure.unsure is False
    groups = duplicate_groups([sure, unsure])
    assert groups and groups[0]["kind"] == "isrc"
    assert groups[0]["duration_mismatch"] is True
    book = LogBook()
    book.add("info", "kész")
    book.add("err", "hiba")
    assert len(book.filtered("err")) == 1
    assert "hiba" in book.text("err")
    assert eta_text(2, 4, 10) == "0:10"
    assert render_filename("{artist} - {title} ({key} {bpm})", {"artist": "A/B", "title": "C:D", "key": "8A", "bpm": "128"}, ".mp3") == "AB - CD (8A 128).mp3"


def test_csv_export_and_unique_names(tmp_path):
    items = [
        Pending(path="/a.mp3", name="a.mp3", status="missed", before={"artist": "A", "title": "B"}, after={}, source="", confidence=0),
        Pending(path="/c.mp3", name="c.mp3", status="ok", before={}, after={"artist": "C", "title": "D"}, source="beatport", confidence=80),
    ]
    dest = tmp_path / "riport.csv"
    assert export_csv(items, dest, only="missed") == 1
    text = dest.read_text(encoding="utf-8")
    assert "fájl,állapot,régi,új,forrás,megbízhatóság" in text
    assert "/a.mp3" in text
    assert "/c.mp3" not in text
    reserved: set[str] = set()
    first = unique_target(tmp_path, "name.mp3", reserved)
    (tmp_path / "name.mp3").write_bytes(b"x")
    reserved.clear()
    second = unique_target(tmp_path, "name.mp3", reserved)
    assert first.name == "name.mp3"
    assert second.name == "name (2).mp3"
