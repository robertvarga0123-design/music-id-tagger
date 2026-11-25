from __future__ import annotations

import asyncio
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from music_id_tagger.covers import cover_hash
from music_id_tagger.match import clean, genre_is_generic, search_identity, to_camelot
from music_id_tagger.tags import AUDIO_EXTENSIONS, read_cover_bytes, read_duration, read_tags, write_tags

LogFn = Callable[[str, str], None]
ProgressFn = Callable[[int, int], None]


@dataclass
class Options:
    use_shazam: bool = True
    use_beatport: bool = True
    beatport_user: str = ""
    beatport_password: str = ""
    use_spotify: bool = False
    spotify_client_id: str = ""
    spotify_client_secret: str = ""
    acoustid_key: str = ""
    grok_key: str = ""
    gemini_key: str = ""
    dry_run: bool = True
    keep_identity: bool = True
    embed_cover: bool = True
    delay: float = 1.0
    beatport_by_file: dict = field(default_factory=dict)
    write_bpm_to_xml: bool = True
    use_open_catalogs: bool = True
    use_deezer: bool = True
    use_apple: bool = True
    use_musicbrainz: bool = True
    use_discogs: bool = True
    use_websearch: bool = False
    defer_write: bool = True
    rescan: bool = False
    fill_missing_only: bool = False
    tag_first: bool = False
    key_format: str = "camelot"
    rename_template: str = ""
    enabled_fields: dict = field(default_factory=dict)
    genre_map: dict = field(default_factory=dict)


@dataclass
class FileResult:
    """One audio file after identify + merge. Safe to serialize; no credentials."""

    name: str
    status: str
    meta: dict = field(default_factory=dict)
    recognized: dict = field(default_factory=dict)
    log: list = field(default_factory=list)
    unsure: bool = False
    source_url: str = ""
    source_label: str = ""


@dataclass
class Stats:
    total: int = 0
    ok: int = 0
    missed: int = 0
    failed: int = 0
    cancelled: bool = False
    files: list[FileResult] = field(default_factory=list)
    by_path: dict = field(default_factory=dict)
    pending: list = field(default_factory=list)
    xmls: list = field(default_factory=list)


_PUBLIC_META_KEYS = (
    "title",
    "artist",
    "album",
    "genre",
    "year",
    "bpm",
    "key",
    "key_name",
    "label",
    "beatport_id",
    "isrc",
    "mix",
    "catalog",
    "cover_url",
    "spotify_id",
    "source",
)


def _public_meta(meta: dict | None) -> dict:
    if not meta:
        return {}
    out: dict = {}
    for key in _PUBLIC_META_KEYS:
        value = meta.get(key)
        if value is None or value == "":
            continue
        if isinstance(value, bool):
            continue
        if isinstance(value, (int, float)):
            out[key] = value
            continue
        if isinstance(value, str):
            text = clean(value)
            if text:
                out[key] = text
    return out


def _push_file(
    stats: Stats,
    name: str,
    status: str,
    meta: dict,
    recognized: dict,
    lines: list,
    unsure: bool = False,
    source_url: str = "",
    source_label: str = "",
) -> None:
    stats.files.append(
        FileResult(
            name=name,
            status=status,
            meta=_public_meta(meta),
            recognized=_public_meta(recognized),
            log=list(lines),
            unsure=unsure,
            source_url=source_url if source_url.startswith("https://") else "",
            source_label=source_label if source_url.startswith("https://") else "",
        )
    )


def collect_files(paths: list[str]) -> list[Path]:
    found: list[Path] = []
    seen: set[str] = set()
    for raw in paths:
        path = Path(raw)
        candidates: list[Path] = []
        if path.is_file():
            candidates = [path]
        elif path.is_dir():
            for dirpath, dirnames, filenames in os.walk(path, followlinks=False):
                dirnames[:] = [name for name in dirnames if not name.startswith(".")]
                for name in filenames:
                    candidates.append(Path(dirpath) / name)
        for candidate in candidates:
            if candidate.name.startswith(".") or candidate.name.startswith("._"):
                continue
            if candidate.suffix.lower() not in AUDIO_EXTENSIONS:
                continue
            try:
                if candidate.stat().st_size < 32_000:
                    continue
            except OSError:
                continue
            key = str(candidate.resolve())
            if key in seen:
                continue
            seen.add(key)
            found.append(candidate)
    found.sort(key=lambda item: str(item).lower())
    return found


def _merge_files(primary: list[Path], extra: list[Path]) -> list[Path]:
    found: list[Path] = []
    seen: set[str] = set()
    for path in [*primary, *extra]:
        try:
            key = os.path.normcase(str(path.resolve()))
        except OSError:
            continue
        if key in seen:
            continue
        seen.add(key)
        found.append(path)
    found.sort(key=lambda item: str(item).lower())
    return found


def _blank(value) -> bool:
    return not clean(value)


def provider_enabled(options: Options, name: str) -> bool:
    """False means that provider is not called at all."""
    if name in {"deezer", "apple", "musicbrainz", "discogs"} and not options.use_open_catalogs:
        return False
    return bool(getattr(options, f"use_{name}", False))


def _without_consumer_genre(meta: dict) -> dict:
    """Drop a broad Shazam or AcoustID genre. A specific one may fill an empty field."""
    cleaned = dict(meta)
    if genre_is_generic(cleaned.get("genre")):
        cleaned.pop("genre", None)
    elif cleaned.get("genre"):
        cleaned["genre_from"] = "other"
    return cleaned


def _keep_fingerprint(meta: dict, existing: dict, filename: str) -> bool:
    from music_id_tagger.match import fingerprint_allowed

    return fingerprint_allowed(clean(meta.get("artist")), clean(meta.get("title")), existing, filename)


def apply_meta(existing: dict, incoming: dict, keep_identity: bool) -> dict:
    """Meglévő és új tagek egyesítése.

    Műfajt felülírni csak a Beatport írhat. Üres mezőbe más forrás is írhat,
    ha a címke nem általános (Dance, Pop, Electronic, Electronica, Music).
    A hangnem és a kiadó csak Beatport-forrásból írja felül a már bent lévőt,
    vagy ha a mező üres. A BPM-et nem Beatport-forrás csak üres mezőbe írja,
    és a fele/duplája tempót (70 vs 140) senki nem írja felül.
    A már bent lévő, eltérő ISRC-t nem cseréljük ki.
    """
    from music_id_tagger.reconcile import bpm_half_time

    merged = dict(existing)
    identity = {"title", "artist", "album"}
    beatport_source = "beatport" in clean(incoming.get("source")).lower()
    for key, value in incoming.items():
        if key in {"source", "match_score", "score", "shazam_id", "cover_hash", "duration", "genre_from"} or value in (
            None,
            "",
        ):
            continue
        if key == "key":
            converted = to_camelot(value)
            if converted:
                if converted != clean(value).upper() and _blank(existing.get("key_name")) and _blank(incoming.get("key_name")):
                    from music_id_tagger.match import camelot_name

                    musical = camelot_name(converted)
                    if musical:
                        merged["key_name"] = musical
                value = converted
        if key in identity and keep_identity and not _blank(existing.get(key)):
            continue
        if key == "year" and keep_identity and not _blank(existing.get(key)):
            continue
        if key == "genre":
            origin = clean(incoming.get("genre_from"))
            from_beatport = origin == "beatport" or (origin != "other" and beatport_source)
            if not from_beatport and (not _blank(existing.get(key)) or genre_is_generic(value)):
                continue
            merged["genre_from"] = "beatport" if from_beatport else "other"
        if key in {"key", "key_name", "label"} and not _blank(existing.get(key)) and not beatport_source:
            continue
        if key == "bpm" and not _blank(existing.get(key)):
            if bpm_half_time(existing.get(key), value) or not beatport_source:
                continue
        if key == "isrc" and not _blank(existing.get(key)):
            if clean(existing.get(key)).upper() != clean(value).upper():
                continue
        merged[key] = value
    sources = [item for item in (existing.get("source"), incoming.get("source")) if item]
    if sources:
        merged["source"] = "+".join(dict.fromkeys("+".join(sources).split("+")))
    return merged


def _line(meta: dict) -> str:
    who = " - ".join(part for part in (clean(meta.get("artist")), clean(meta.get("title"))) if part)
    bits = [who or "(nincs cím)"]
    if meta.get("bpm"):
        bits.append(f"{meta['bpm']} BPM")
    if meta.get("key"):
        bits.append(str(meta["key"]))
    if meta.get("genre"):
        bits.append(str(meta["genre"]))
    if meta.get("beatport_id"):
        bits.append(f"BP {meta['beatport_id']}")
    return " | ".join(bits)


def _file_key(path: Path) -> str:
    try:
        return str(path.resolve())
    except OSError:
        return str(path)


def _emit(track, key: str, name: str, state: str, detail: str, url: str, label: str) -> None:
    if track is None:
        return
    safe_url = url if isinstance(url, str) and url.startswith("https://") else ""
    track(
        {
            "path": key,
            "name": name,
            "state": state,
            "detail": detail,
            "url": safe_url,
            "label": label if safe_url else "",
        }
    )


def _source_label(url: str, beatport_id: str = "") -> str:
    ident = clean(beatport_id)
    if "beatport.com" in url or ident:
        return f"Beatport {ident}".strip() if "beatport.com" in url or ident else "Beatport"
    if "spotify.com" in url:
        return "Spotify"
    if "deezer.com" in url:
        return "Deezer"
    if "music.apple.com" in url or "itunes.apple.com" in url:
        return "Apple"
    if "musicbrainz.org" in url:
        return "MusicBrainz"
    if "discogs.com" in url:
        return "Discogs"
    if "shazam.com" in url:
        return "Shazam"
    return "Forrás" if url else ""


def _audio_id(found: dict) -> bool:
    source = clean(found.get("source")).lower()
    return "shazam" in source or "acoustid" in source


def _take(
    found: dict,
    hit: dict | None,
    artist: str,
    title: str,
    flog: LogFn,
    *,
    file_duration=None,
    file_cover_hash: str | None = None,
) -> str:
    from music_id_tagger.reconcile import merge_hit

    if not hit:
        return "rejected"
    status = merge_hit(
        found,
        hit,
        artist,
        title,
        audio=_audio_id(found),
        file_duration=file_duration,
        file_cover_hash=file_cover_hash,
    )
    who = " - ".join(part for part in (clean(hit.get("artist")), clean(hit.get("title"))) if part) or "ismeretlen"
    if status == "accepted":
        bits = [str(item) for item in (hit.get("bpm") and f"{hit.get('bpm')} BPM", hit.get("key"), hit.get("isrc")) if item]
        extra = f" ({', '.join(bits)})" if bits else ""
        flog("ok", f"{clean(hit.get('source')) or 'Katalógus'}: {who}{extra}")
    elif status == "weak":
        flog("muted", f"Gyenge találat, a BPM és a műfaj marad: {who}")
    elif status == "duration":
        flog("muted", f"Eltérő hossz, kihagyva: {who}")
    elif status == "cover":
        flog("muted", f"A borító nem egyezik, kihagyva: {who}")
    else:
        flog("muted", f"Eltérő találat, kihagyva: {who}")
    if status in {"duration", "cover"}:
        return "rejected"
    return status


def _needs(found: dict, *keys: str) -> bool:
    return any(_blank(found.get(key)) for key in keys)


async def _open_catalogs(
    found: dict,
    artist: str,
    title: str,
    stage,
    flog: LogFn,
    options: Options,
    *,
    file_duration=None,
    file_cover_hash: str | None = None,
) -> None:
    """Fill the holes Beatport and Spotify left. Never required for a file to succeed."""
    from music_id_tagger import catalogs

    def take(hit: dict | None) -> str:
        return _take(
            found,
            hit,
            artist,
            title,
            flog,
            file_duration=file_duration,
            file_cover_hash=file_cover_hash,
        )

    isrc = clean(found.get("isrc"))
    if isrc and provider_enabled(options, "deezer") and _needs(found, "album", "year", "bpm", "label"):
        stage("deezer")
        take(await asyncio.to_thread(catalogs.deezer_by_isrc, isrc, flog))
    if isrc and provider_enabled(options, "musicbrainz") and _needs(found, "album", "year"):
        stage("musicbrainz")
        take(await asyncio.to_thread(catalogs.musicbrainz_by_isrc, isrc, flog))
    if (
        artist
        and title
        and provider_enabled(options, "deezer")
        and "deezer" not in clean(found.get("source"))
        and _needs(found, "bpm", "isrc", "album", "year")
    ):
        stage("deezer")
        take(await asyncio.to_thread(catalogs.deezer_search, artist, title, flog, file_duration))
    if artist and title and provider_enabled(options, "apple") and _needs(found, "album", "year"):
        stage("apple")
        take(await asyncio.to_thread(catalogs.itunes_search, artist, title, flog, file_duration))
    if (
        artist
        and title
        and provider_enabled(options, "musicbrainz")
        and "musicbrainz" not in clean(found.get("source"))
        and _needs(found, "album", "year", "isrc")
    ):
        stage("musicbrainz")
        take(await asyncio.to_thread(catalogs.musicbrainz_search, artist, title, flog, file_duration))
    if (
        artist
        and title
        and provider_enabled(options, "discogs")
        and "discogs" not in clean(found.get("source"))
        and _needs(found, "album", "year", "label", "catalog")
    ):
        stage("discogs")
        take(await asyncio.to_thread(catalogs.discogs_search, artist, title, flog, file_duration))


def _forced_beatport_id(path: Path, options: Options) -> str:
    table = options.beatport_by_file or {}
    keys = [str(path), path.name]
    try:
        keys.insert(0, str(path.resolve()))
    except OSError:
        pass
    for key in keys:
        ident = ""
        raw = table.get(key)
        if raw:
            from music_id_tagger.beatport import parse_beatport_id

            ident = parse_beatport_id(raw) or ""
        if ident:
            return ident
    return ""


async def _web_beatport(found, artist, title, beatport, take, stage, flog) -> None:
    """When the Beatport search misses, look the track up on the web and open that id."""
    from music_id_tagger.websearch import beatport_ids

    stage("web")
    ids = await asyncio.to_thread(beatport_ids, artist, title, flog)
    for ident in ids:
        hit = await asyncio.to_thread(beatport.by_id, ident, flog)
        if not hit:
            continue
        hit = dict(hit)
        # Not 100: the page has to match the filename and the length. A pasted link stays exact.
        hit["match_score"] = 18
        if take(hit, artist, title) == "accepted" and found.get("beatport_id"):
            flog("ok", f"Beatport a webes keresésből: {found.get('beatport_id')}")
            return


def run(
    paths: list[str],
    options: Options,
    log: LogFn,
    progress: ProgressFn,
    cancel,
    track: Callable[[dict], None] | None = None,
) -> Stats:
    from music_id_tagger.undo import begin_run, commit_run

    begin_run()
    try:
        return _run(paths, options, log, progress, cancel, track)
    finally:
        commit_run()


def _run(
    paths: list[str],
    options: Options,
    log: LogFn,
    progress: ProgressFn,
    cancel,
    track: Callable[[dict], None] | None = None,
) -> Stats:
    from music_id_tagger.rekordbox import audio_from_xml, collect_xml, update_library

    stats = Stats()
    xmls = collect_xml(paths)
    files = _merge_files(collect_files(paths), audio_from_xml(xmls))
    stats.total = len(files)
    if xmls:
        log("info", f"Rekordbox XML: {len(xmls)} lista.")
    if not files:
        log("err", "Nincs audio fájl a megadott helyeken." if not xmls else "A Rekordbox listában egy hangfájl sem található a gépen.")
        progress(0, 0)
        return stats
    log(
        "info",
        f"{len(files)} fájl. "
        + (
            "Keresés. A fájlok még nem változnak."
            if options.dry_run or getattr(options, "defer_write", True)
            else "A tagek beíródnak a fájlokba."
        ),
    )
    for path in files:
        _emit(track, _file_key(path), path.name, "wait", "", "", "")

    beatport = None
    if options.use_beatport and options.beatport_user and options.beatport_password:
        log("info", "Beatport belépés…")
        try:
            from music_id_tagger.beatport import BeatportClient

            beatport = BeatportClient()
            beatport.login(options.beatport_user, options.beatport_password)
            log("ok", "Beatport belépés kész.")
        except Exception as exc:
            beatport = None
            log("err", f"Beatport belépés nem sikerült: {exc}")
    elif options.use_beatport:
        log("muted", "Beatport be van kapcsolva, de nincs felhasználónév vagy jelszó.")

    spotify = None
    if options.use_spotify and options.spotify_client_id and options.spotify_client_secret:
        log("info", "Spotify belépés…")
        try:
            from music_id_tagger.spotify import SpotifyClient

            spotify = SpotifyClient()
            spotify.login(options.spotify_client_id, options.spotify_client_secret)
            log("ok", "Spotify belépés kész.")
        except Exception as exc:
            spotify = None
            log("err", f"Spotify belépés nem sikerült: {exc}")
    elif options.use_spotify:
        log("muted", "Spotify be van kapcsolva, de nincs Client ID vagy Client Secret.")
    if options.grok_key or options.gemini_key:
        both = bool(options.grok_key and options.gemini_key)
        log(
            "info",
            "Két AI dönt a bizonytalan találatoknál: csak akkor írunk, ha mindkettő elfogadja."
            if both
            else "Egy AI kulcs van meg. A döntése sárga marad, amíg a Grok és a Gemini kulcs is bent van.",
        )
    if options.use_open_catalogs:
        names = [
            label
            for label, key in (
                ("Deezer", "deezer"),
                ("Apple", "apple"),
                ("MusicBrainz", "musicbrainz"),
                ("Discogs", "discogs"),
            )
            if provider_enabled(options, key)
        ]
        if names:
            log("info", f"{', '.join(names)} bekapcsolva. Ezekhez nem kell kulcs.")
    if options.use_websearch:
        log("muted", "Webes keresés bekapcsolva: a számcímek a Bingnek kerülnek.")

    try:
        asyncio.run(_process(files, options, beatport, spotify, log, progress, cancel, stats, track))
    except Exception as exc:
        stats.failed += 1
        log("err", f"A feldolgozás megszakadt: {exc}")
    if cancel.is_set():
        stats.cancelled = True
        log("muted", "Megállítva.")
    elif not getattr(options, "defer_write", True):
        for xml in xmls:
            try:
                changed, missing, notes = update_library(
                    xml, stats.by_path, options.keep_identity, options.dry_run, options.write_bpm_to_xml
                )
            except Exception as exc:
                stats.failed += 1
                log("err", f"Rekordbox XML hiba ({xml.name}): {exc}")
                continue
            prefix = "PRÓBA XML" if options.dry_run else "XML ÍRVA"
            log("info", f"{prefix}: {xml.name} — {changed} szám javítva, {missing} fájl hiányzik.")
            for note in notes:
                log("ok", note)
            if changed and not options.dry_run:
                log("ok", f"Biztonsági másolat: {xml.name}.bak")
    elif xmls:
        log("muted", "A Rekordbox XML az Alkalmazás lépésben frissül.")
    stats.xmls = [str(item) for item in xmls]
    if getattr(options, "defer_write", True):
        mode = "Az írás külön lépés, a fájlok még nem változtak."
    elif options.dry_run:
        mode = "A fájlok nem változtak."
    else:
        mode = "A találatok be lettek írva."
    log(
        "info",
        f"Kész. Siker: {stats.ok}, nincs találat: {stats.missed}, hiba: {stats.failed}. {mode}",
    )
    return stats


async def _process(files, options: Options, beatport, spotify, log: LogFn, progress: ProgressFn, cancel, stats: Stats, track) -> None:
    shazam = None
    context = None
    if options.use_shazam:
        try:
            from shazamio import Shazam

            context = Shazam()
            shazam = await context.__aenter__()
        except Exception as exc:
            log("err", f"A Shazam nem indult el: {exc}")
            shazam = None
            context = None
    try:
        for index, path in enumerate(files, start=1):
            if cancel.is_set():
                break
            progress(index - 1, stats.total)
            _emit(track, _file_key(path), path.name, "run", "", "", "")
            try:
                await _one(path, options, beatport, spotify, shazam, log, stats, track)
            except Exception as exc:
                stats.failed += 1
                message = f"Hiba: {path.name} — {exc}"
                log("err", message)
                if not any(item.name == path.name for item in stats.files):
                    _push_file(
                        stats,
                        path.name,
                        "failed",
                        {},
                        {},
                        [{"level": "err", "message": message}],
                        unsure=True,
                    )
                    _emit(track, _file_key(path), path.name, "failed", "Hiba", "", "")
            progress(index, stats.total)
            if index < len(files) and not cancel.is_set():
                await _sleep(max(0.0, options.delay), cancel)
    finally:
        if context is not None:
            await context.__aexit__(None, None, None)


def _beatport_rows(beatport, artist: str, title: str, flog: LogFn, file_duration) -> tuple[dict | None, list]:
    """Top matches from one search. Stubs without ``ranked`` still work."""
    ranked = getattr(beatport, "ranked", None)
    if callable(ranked):
        try:
            raw = ranked(artist, title, flog, file_duration)
        except TypeError:
            raw = ranked(artist, title, flog)
        rows = [item for item in raw if isinstance(item, dict)] if isinstance(raw, list) else []
        return (rows[0] if rows else None), rows
    search = getattr(beatport, "search", None)
    if not callable(search):
        return None, []
    try:
        hit = search(artist, title, flog, file_duration)
    except TypeError:
        hit = search(artist, title, flog)
    if isinstance(hit, list):
        rows = [item for item in hit if isinstance(item, dict)]
        return (rows[0] if rows else None), rows
    if isinstance(hit, dict):
        return hit, [hit]
    return None, []


def _jsonable_meta(meta: dict | None) -> dict:
    out: dict = {}
    for key, value in (meta or {}).items():
        if isinstance(value, bool) or value is None:
            continue
        if isinstance(value, (str, int, float)):
            out[str(key)] = value
    return out


def _public_candidate(item: dict) -> dict:
    out: dict = {}
    for key in (
        "title",
        "artist",
        "mix",
        "bpm",
        "key",
        "genre",
        "cover_url",
        "label",
        "isrc",
        "beatport_id",
        "source_url",
        "match_score",
    ):
        value = item.get(key)
        if isinstance(value, bool) or value in (None, ""):
            continue
        out[key] = value if isinstance(value, (str, int, float)) else str(value)
    if "match_score" in out:
        out["score"] = out["match_score"]
    return out


def _remember(path: Path, found: dict, candidates: list, guessed: bool, origin: str, status: str, unsure: bool, flog: LogFn) -> None:
    try:
        from music_id_tagger.cache import store

        store(
            path,
            {
                "found": _jsonable_meta(found),
                "candidates": [_public_candidate(item) for item in candidates if isinstance(item, dict)],
                "guessed": bool(guessed),
                "origin": origin or "",
                "status": status,
            },
            clean(found.get("source")),
            bool(unsure),
        )
    except Exception as exc:
        flog("muted", f"Cache írás kihagyva: {exc}")


def _record_pending(
    stats: Stats,
    path: Path,
    status: str,
    before: dict,
    after: dict,
    found: dict,
    unsure: bool,
    candidates: list,
    url: str,
    label: str,
    duration,
    options: Options,
) -> None:
    from music_id_tagger.pending import Pending, confidence_of, preview_changes

    try:
        shown = str(path.resolve())
    except OSError:
        shown = str(path)
    item = Pending(
        path=shown,
        name=path.name,
        status=status,
        before=_jsonable_meta(before),
        after=_jsonable_meta(after),
        source=clean((found or {}).get("source")),
        confidence=confidence_of(found, unsure, status),
        unsure=bool(unsure) or status == "unsure",
        candidates=[_public_candidate(row) for row in candidates if isinstance(row, dict)],
        source_url=url if isinstance(url, str) and url.startswith("https://") else "",
        source_label=label if isinstance(url, str) and url.startswith("https://") else "",
        duration=duration if isinstance(duration, (int, float)) and not isinstance(duration, bool) else None,
    )
    item.changed = preview_changes(
        item,
        getattr(options, "enabled_fields", None) or {},
        bool(getattr(options, "fill_missing_only", False)),
        getattr(options, "key_format", "camelot") or "camelot",
        getattr(options, "genre_map", None) or {},
    )
    stats.pending.append(item)


def _skip_filled(path, options, existing, has_cover, flog, stats, track, lines, file_duration) -> bool:
    if not getattr(options, "fill_missing_only", False):
        return False
    from music_id_tagger.pending import needs_lookup

    if needs_lookup(existing, getattr(options, "enabled_fields", None) or {}, has_cover):
        return False
    flog("muted", f"Minden kért mező megvan, kihagyom: {path.name}")
    _record_pending(stats, path, "skipped", existing, existing, {}, False, [], "", "", file_duration, options)
    _push_file(stats, path.name, "skipped", existing, {}, lines, unsure=False)
    _emit(track, _file_key(path), path.name, "ok", "Kihagyva, megvan", "", "")
    return True


async def _finish_file(
    path: Path,
    options: Options,
    existing: dict,
    found: dict,
    lines: list,
    guessed: bool,
    origin: str,
    candidates: list,
    flog: LogFn,
    stats: Stats,
    track,
    forced: bool,
    file_duration,
    stage,
    *,
    from_cache: bool = False,
    cached_status: str = "",
    cached_unsure: bool = False,
) -> None:
    from music_id_tagger.beatport import parse_beatport_id
    from music_id_tagger.match import is_uncertain

    ident = parse_beatport_id(found.get("source_url")) or parse_beatport_id(found.get("beatport_id"))
    if ident:
        found["beatport_id"] = ident
        if "beatport.com/track/" not in clean(found.get("source_url")):
            found["source_url"] = f"https://www.beatport.com/track/{ident}"
    url = clean(found.get("source_url"))
    label = _source_label(url, ident or "")
    useful = any(found.get(key) for key in ("title", "artist", "genre", "bpm", "key", "beatport_id"))
    if from_cache and cached_status in {"missed", "rejected"}:
        useful = False
    defer = getattr(options, "defer_write", True)
    weak = not useful and bool(candidates) and (not from_cache or cached_status == "unsure")
    if not useful and not weak:
        if not from_cache:
            _remember(path, found, candidates, guessed, origin, "missed", True, flog)
        stats.missed += 1
        flog("muted", f"Nincs találat: {path.name}")
        _record_pending(stats, path, "missed", existing, existing, found, True, candidates, url, label, file_duration, options)
        _push_file(stats, path.name, "missed", existing, found, lines, unsure=True, source_url=url, source_label=label)
        _emit(track, _file_key(path), path.name, "missed", "Nincs találat", url, label)
        return

    final_keep = options.keep_identity and origin != "conflict-file"
    if origin == "conflict-file" and options.keep_identity:
        flog("muted", "A bent lévő cím nem a fájlnévhez tartozik, a találat cseréli.")
    if from_cache:
        unsure = bool(cached_unsure) or weak
    else:
        unsure = True if weak else is_uncertain(found, guessed)
    if useful and (options.grok_key or options.gemini_key) and not forced and not from_cache and unsure:
        stage("ai")
        from music_id_tagger.judge import review

        verdict = await asyncio.to_thread(
            review,
            path.name,
            existing,
            found,
            file_duration,
            options.grok_key,
            options.gemini_key,
            flog,
        )
        if verdict.used and not verdict.accept:
            _remember(path, found, candidates, guessed, origin, "missed", True, flog)
            stats.missed += 1
            flog("muted", f"AI nem engedi a találatot, a fájl marad: {path.name}")
            _record_pending(stats, path, "missed", existing, existing, found, True, candidates, url, label, file_duration, options)
            _push_file(stats, path.name, "missed", existing, found, lines, unsure=True, source_url=url, source_label=label)
            _emit(track, _file_key(path), path.name, "rejected", "AI elutasította", url, label)
            return
        if verdict.confirmed >= 2:
            unsure = False
        elif verdict.confirmed == 1:
            unsure = True
    final = apply_meta(existing, found, keep_identity=final_keep) if useful else dict(existing)
    if unsure and not weak:
        flog("muted", f"Bizonytalan találat, nézd meg a forrást: {path.name}")
    if weak:
        flog("muted", f"Bizonytalan Beatport-találatok, válassz: {path.name}")
    if not defer and useful:
        prefix = "PRÓBA" if options.dry_run else "ÍRVA"
        stage("write")
        try:
            await asyncio.to_thread(write_tags, path, final, options.dry_run, options.embed_cover)
        except Exception as exc:
            stats.failed += 1
            flog("err", f"Tag írás hiba ({path.name}): {exc}")
            _record_pending(stats, path, "failed", existing, final, found, True, candidates, url, label, file_duration, options)
            _push_file(stats, path.name, "failed", final, found, lines, unsure=True, source_url=url, source_label=label)
            _emit(track, _file_key(path), path.name, "failed", "Hiba", url, label)
            return
        try:
            from music_id_tagger.rekordbox import path_key

            stats.by_path[path_key(path)] = final
        except OSError:
            pass
    else:
        prefix = "TERV"
    if not from_cache:
        _remember(path, found, candidates, guessed, origin, "unsure" if weak else "ok", unsure or weak, flog)
    stats.ok += 1
    flog("ok", f"{prefix}: {path.name} → {_line(final)}")
    state = "unsure" if unsure or weak else "ok"
    row_status = "unsure" if weak else "ok"
    _record_pending(stats, path, row_status, existing, final, found, unsure or weak, candidates, url, label, file_duration, options)
    _push_file(stats, path.name, row_status, final, found, lines, unsure=unsure or weak, source_url=url, source_label=label)
    _emit(track, _file_key(path), path.name, state, _line(final), url, label)


async def _one(path: Path, options: Options, beatport, spotify, shazam, log: LogFn, stats: Stats, track) -> None:
    lines: list[dict[str, str]] = []

    def flog(level: str, message: str) -> None:
        lines.append({"level": level, "message": message})
        log(level, message)

    existing = read_tags(path)
    found: dict = {}
    file_duration = read_duration(path)
    file_cover_hash = cover_hash(read_cover_bytes(path))
    candidates: list = []
    searched_beatport = False
    tag_artist = clean(existing.get("artist"))
    tag_title = clean(existing.get("title"))

    def take(hit: dict | None, artist: str, title: str) -> str:
        return _take(
            found,
            hit,
            artist,
            title,
            flog,
            file_duration=file_duration,
            file_cover_hash=file_cover_hash,
        )

    def stage(name: str) -> None:
        _emit(track, _file_key(path), path.name, name, "", "", "")

    if _skip_filled(path, options, existing, bool(file_cover_hash), flog, stats, track, lines, file_duration):
        return
    if not getattr(options, "rescan", False):
        try:
            from music_id_tagger.cache import lookup

            payload = lookup(path)
        except Exception:
            payload = None
        if isinstance(payload, dict):
            flog("muted", f"Cache találat, nincs hálózati hívás: {path.name}")
            cached_found = dict(payload.get("found") or {})
            cached_rows = payload.get("candidates") if isinstance(payload.get("candidates"), list) else []
            await _finish_file(
                path,
                options,
                existing,
                cached_found,
                lines,
                bool(payload.get("guessed")),
                str(payload.get("origin") or ""),
                cached_rows,
                flog,
                stats,
                track,
                True,
                file_duration,
                stage,
                from_cache=True,
                cached_status=str(payload.get("status") or ""),
                cached_unsure=bool(payload.get("unsure")),
            )
            return

    tag_first = bool(getattr(options, "tag_first", False))
    if tag_first and tag_artist and tag_title and provider_enabled(options, "beatport") and beatport is not None:
        stage("beatport")
        hit, rows = await asyncio.to_thread(_beatport_rows, beatport, tag_artist, tag_title, flog, file_duration)
        candidates = rows
        searched_beatport = True
        if hit:
            take(hit, tag_artist, tag_title)

    if options.use_shazam and shazam is not None and not (tag_first and found.get("beatport_id")):
        stage("shazam")
        try:
            from music_id_tagger.identify import recognize_shazam

            recognized = await asyncio.wait_for(recognize_shazam(shazam, path), timeout=45)
            if recognized and _keep_fingerprint(recognized, existing, path.name):
                found = apply_meta(found, _without_consumer_genre(recognized), keep_identity=False)
                flog(
                    "ok",
                    f"Shazam: {path.name} → {clean(recognized.get('artist'))} - {clean(recognized.get('title'))}",
                )
            elif recognized:
                flog(
                    "muted",
                    "Shazam nem egyezik a fájlnévvel vagy a taggel, kihagyom: "
                    f"{clean(recognized.get('artist'))} - {clean(recognized.get('title'))}",
                )
            else:
                flog("muted", f"Shazam: nincs találat — {path.name}")
        except TimeoutError:
            flog("err", f"Shazam időtúllépés ({path.name}), megyek tovább.")
        except Exception as exc:
            flog("err", f"Shazam hiba ({path.name}): {exc}")

    if options.acoustid_key and "shazam" not in clean(found.get("source")):
        stage("acoustid")
        try:
            from music_id_tagger.identify import identify_acoustid

            acoust = await asyncio.to_thread(identify_acoustid, path, options.acoustid_key.strip())
            if acoust and _keep_fingerprint(acoust, existing, path.name):
                found = apply_meta(found, _without_consumer_genre(acoust), keep_identity=False)
                flog("ok", f"AcoustID: {clean(acoust.get('artist'))} - {clean(acoust.get('title'))}")
            elif acoust:
                flog(
                    "muted",
                    "AcoustID nem egyezik a fájlnévvel vagy a taggel, kihagyom: "
                    f"{clean(acoust.get('artist'))} - {clean(acoust.get('title'))}",
                )
            else:
                flog("muted", f"AcoustID: nincs találat — {path.name}")
        except Exception as exc:
            flog("err", f"AcoustID hiba ({path.name}): {exc}")

    local_artist, local_title, origin = search_identity(existing, path.name)
    if origin == "conflict-file":
        query_artist, query_title = local_artist, local_title
        guessed = True
        flog("muted", f"A fájlnév és a tag eltér. A fájlnév alapján keresek: {local_artist} - {local_title}")
    elif clean(found.get("artist")) and clean(found.get("title")):
        query_artist = clean(found.get("artist"))
        query_title = clean(found.get("title"))
        guessed = False
    elif origin in {"tag", "file"}:
        query_artist, query_title = local_artist, local_title
        guessed = origin == "file"
    else:
        query_artist, query_title = "", ""
        guessed = False

    forced = _forced_beatport_id(path, options)
    if provider_enabled(options, "beatport") and beatport is not None and forced:
        hit = await asyncio.to_thread(beatport.by_id, forced, flog)
        if hit:
            from music_id_tagger.reconcile import durations_compatible

            if durations_compatible(file_duration, hit.get("duration")) is False:
                flog("muted", "A megadott Beatport-szám hossza eltér a fájltól, de a linket használom.")
            for key in (
                "title",
                "artist",
                "genre",
                "bpm",
                "key",
                "key_name",
                "label",
                "beatport_id",
                "isrc",
                "mix",
                "catalog",
                "cover_url",
                "album",
                "year",
                "duration",
                "source_url",
            ):
                if hit.get(key):
                    found[key] = hit[key]
            found["beatport_id"] = forced
            found["match_score"] = 100
            if hit.get("genre"):
                found["genre_from"] = "beatport"
            previous = found.get("source")
            found["source"] = "beatport" if not previous else f"{previous}+beatport"
            guessed = False
            flog("ok", f"Beatport ID {forced}: {clean(hit.get('artist'))} - {clean(hit.get('title'))}")

    isrc = clean(found.get("isrc"))
    if provider_enabled(options, "beatport") and beatport is not None and isrc and not found.get("beatport_id"):
        stage("beatport")
        hit = await asyncio.to_thread(beatport.by_isrc, isrc, flog)
        if hit:
            hit["match_score"] = 100
            if take(hit, query_artist or clean(hit.get("artist")), query_title or clean(hit.get("title"))) == "accepted":
                guessed = False
                flog("ok", f"Beatport ID a hangmintából: {found.get('beatport_id')}")

    if provider_enabled(options, "spotify") and spotify is not None and query_artist and query_title:
        stage("spotify")
        hit = await asyncio.to_thread(spotify.search, query_artist, query_title, flog, file_duration)
        take(hit, query_artist, query_title)

    if (
        provider_enabled(options, "beatport")
        and beatport is not None
        and query_artist
        and query_title
        and not found.get("beatport_id")
        and not (
            searched_beatport
            and clean(query_artist).lower() == tag_artist.lower()
            and clean(query_title).lower() == tag_title.lower()
        )
    ):
        stage("beatport")
        hit, rows = await asyncio.to_thread(_beatport_rows, beatport, query_artist, query_title, flog, file_duration)
        if rows:
            candidates = rows
        take(hit, query_artist, query_title)

    if (
        provider_enabled(options, "websearch")
        and provider_enabled(options, "beatport")
        and beatport is not None
        and query_artist
        and query_title
        and not found.get("beatport_id")
    ):
        await _web_beatport(found, query_artist, query_title, beatport, take, stage, flog)

    if options.use_open_catalogs:
        await _open_catalogs(
            found,
            query_artist,
            query_title,
            stage,
            flog,
            options,
            file_duration=file_duration,
            file_cover_hash=file_cover_hash,
        )

    isrc_now = clean(found.get("isrc"))
    if provider_enabled(options, "beatport") and beatport is not None and isrc_now and not found.get("beatport_id"):
        stage("beatport")
        hit = await asyncio.to_thread(beatport.by_isrc, isrc_now, flog)
        if hit:
            hit["match_score"] = 100
            if take(hit, query_artist or clean(hit.get("artist")), query_title or clean(hit.get("title"))) == "accepted":
                if found.get("beatport_id"):
                    flog("ok", f"Beatport ID a katalógus ISRC-jéből: {found.get('beatport_id')}")

    await _finish_file(
        path,
        options,
        existing,
        found,
        lines,
        guessed,
        origin,
        candidates,
        flog,
        stats,
        track,
        bool(forced),
        file_duration,
        stage,
    )


async def _sleep(seconds: float, cancel) -> None:
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if cancel.is_set():
            return
        await asyncio.sleep(min(0.2, max(0.0, end - time.monotonic())))
