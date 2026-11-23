from __future__ import annotations

import asyncio
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from music_id_tagger.match import clean, parse_filename
from music_id_tagger.tags import AUDIO_EXTENSIONS, read_tags, write_tags

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
    dry_run: bool = True
    keep_identity: bool = True
    embed_cover: bool = True
    delay: float = 1.0
    beatport_by_file: dict = field(default_factory=dict)


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


def apply_meta(existing: dict, incoming: dict, keep_identity: bool) -> dict:
    merged = dict(existing)
    identity = {"title", "artist", "album"}
    for key, value in incoming.items():
        if key in {"source", "match_score", "score", "shazam_id"} or value in (None, ""):
            continue
        if key in identity and keep_identity and not _blank(existing.get(key)):
            continue
        if key == "year" and keep_identity and not _blank(existing.get(key)):
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


def _remember_hit(found: dict, hit: dict) -> None:
    url = clean(hit.get("source_url"))
    if url.startswith("https://"):
        found["source_url"] = url
    if hit.get("match_score") not in (None, ""):
        found["match_score"] = hit["match_score"]


def _source_label(url: str, beatport_id: str = "") -> str:
    ident = clean(beatport_id)
    if "beatport.com" in url or ident:
        return f"Beatport {ident}".strip() if "beatport.com" in url or ident else "Beatport"
    if "spotify.com" in url:
        return "Spotify"
    if "shazam.com" in url:
        return "Shazam"
    if "musicbrainz.org" in url:
        return "MusicBrainz"
    return "Forrás" if url else ""


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


def run(
    paths: list[str],
    options: Options,
    log: LogFn,
    progress: ProgressFn,
    cancel,
    track: Callable[[dict], None] | None = None,
) -> Stats:
    from music_id_tagger.rekordbox import audio_from_xml, collect_xml, path_key, update_library

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
        f"{len(files)} fájl. {'Próba mód, semmi nem íródik.' if options.dry_run else 'A tagek beíródnak a fájlokba.'}",
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

    try:
        asyncio.run(_process(files, options, beatport, spotify, log, progress, cancel, stats, track))
    except Exception as exc:
        stats.failed += 1
        log("err", f"A feldolgozás megszakadt: {exc}")
    if cancel.is_set():
        stats.cancelled = True
        log("muted", "Megállítva.")
    else:
        for xml in xmls:
            try:
                changed, missing, notes = update_library(xml, stats.by_path, options.keep_identity, options.dry_run)
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
    mode = "A fájlok nem változtak." if options.dry_run else "A találatok be lettek írva."
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


async def _one(path: Path, options: Options, beatport, spotify, shazam, log: LogFn, stats: Stats, track) -> None:
    lines: list[dict[str, str]] = []

    def flog(level: str, message: str) -> None:
        lines.append({"level": level, "message": message})
        log(level, message)

    existing = read_tags(path)
    found: dict = {}

    def stage(name: str) -> None:
        _emit(track, _file_key(path), path.name, name, "", "", "")

    if shazam is not None:
        stage("shazam")
        try:
            from music_id_tagger.identify import recognize_shazam

            recognized = await recognize_shazam(shazam, path)
            if recognized:
                found = apply_meta(found, recognized, keep_identity=False)
                flog(
                    "ok",
                    f"Shazam: {path.name} → {clean(recognized.get('artist'))} - {clean(recognized.get('title'))}",
                )
            else:
                flog("muted", f"Shazam: nincs találat — {path.name}")
        except Exception as exc:
            flog("err", f"Shazam hiba ({path.name}): {exc}")

    query_artist = clean(found.get("artist")) or clean(existing.get("artist"))
    query_title = clean(found.get("title")) or clean(existing.get("title"))
    guessed = False
    if not query_artist or not query_title:
        parsed = parse_filename(path.name)
        if parsed:
            query_artist = query_artist or parsed[0]
            query_title = query_title or parsed[1]
            guessed = True

    forced = _forced_beatport_id(path, options)
    if beatport is not None and forced:
        hit = await asyncio.to_thread(beatport.by_id, forced, flog)
        if hit:
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
                "source_url",
            ):
                if hit.get(key):
                    found[key] = hit[key]
            found["beatport_id"] = forced
            found["match_score"] = 100
            previous = found.get("source")
            found["source"] = "beatport" if not previous else f"{previous}+beatport"
            guessed = False
            flog("ok", f"Beatport ID {forced}: {clean(hit.get('artist'))} - {clean(hit.get('title'))}")

    isrc = clean(found.get("isrc"))
    if beatport is not None and isrc and not found.get("beatport_id"):
        stage("beatport")
        hit = await asyncio.to_thread(beatport.by_isrc, isrc, flog)
        if hit:
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
                "source_url",
            ):
                if hit.get(key):
                    found[key] = hit[key]
            found["match_score"] = 100
            previous = found.get("source")
            found["source"] = "beatport" if not previous else f"{previous}+beatport"
            guessed = False
            flog("ok", f"Beatport ID a hangmintából: {found.get('beatport_id')} — {clean(hit.get('artist'))} - {clean(hit.get('title'))}")

    if spotify is not None and query_artist and query_title:
        stage("spotify")
        hit = await asyncio.to_thread(spotify.search, query_artist, query_title, flog)
        if hit:
            if guessed and not found.get("title"):
                found["title"] = hit.get("title")
                found["artist"] = hit.get("artist")
            for key in ("album", "year", "isrc", "cover_url", "spotify_id", "bpm", "key", "key_name"):
                if hit.get(key) and not found.get(key):
                    found[key] = hit[key]
            if not found.get("title"):
                found["title"] = hit.get("title")
            if not found.get("artist"):
                found["artist"] = hit.get("artist")
            previous = found.get("source")
            found["source"] = "spotify" if not previous else f"{previous}+spotify"
            _remember_hit(found, hit)
            flog("ok", f"Spotify: {clean(hit.get('artist'))} - {clean(hit.get('title'))} | {hit.get('isrc') or 'nincs ISRC'}")

    if beatport is not None and query_artist and query_title and not found.get("beatport_id"):
        stage("beatport")
        hit = await asyncio.to_thread(beatport.search, query_artist, query_title, flog)
        if hit:
            if guessed and not found.get("title"):
                found["title"] = hit.get("title")
                found["artist"] = hit.get("artist")
            for key in (
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
            ):
                if hit.get(key):
                    found[key] = hit[key]
            if not found.get("title"):
                found["title"] = hit.get("title")
            if not found.get("artist"):
                found["artist"] = hit.get("artist")
            previous = found.get("source")
            found["source"] = "beatport" if not previous else f"{previous}+beatport"
            _remember_hit(found, hit)
            flog(
                "ok",
                f"Beatport: {hit.get('bpm') or '–'} BPM, {hit.get('key') or '–'}, {hit.get('genre') or '–'}",
            )

    if options.acoustid_key and (_blank(found.get("title")) or _blank(found.get("artist"))):
        try:
            from music_id_tagger.identify import identify_acoustid

            acoust = await asyncio.to_thread(identify_acoustid, path, options.acoustid_key.strip())
            if acoust:
                found = apply_meta(found, acoust, keep_identity=False)
                flog("ok", f"AcoustID: {clean(acoust.get('artist'))} - {clean(acoust.get('title'))}")
        except Exception as exc:
            flog("err", f"AcoustID hiba ({path.name}): {exc}")

    useful = any(found.get(key) for key in ("title", "artist", "genre", "bpm", "key", "beatport_id"))
    from music_id_tagger.beatport import parse_beatport_id
    from music_id_tagger.match import is_uncertain

    ident = parse_beatport_id(found.get("source_url")) or parse_beatport_id(found.get("beatport_id"))
    if ident:
        found["beatport_id"] = ident
        if "beatport.com/track/" not in clean(found.get("source_url")):
            found["source_url"] = f"https://www.beatport.com/track/{ident}"
    url = clean(found.get("source_url"))
    label = _source_label(url, ident or "")
    if not useful:
        stats.missed += 1
        flog("muted", f"Nincs találat: {path.name}")
        _push_file(stats, path.name, "missed", existing, found, lines, unsure=True, source_url=url, source_label=label)
        _emit(track, _file_key(path), path.name, "missed", "Nincs találat", url, label)
        return

    final = apply_meta(existing, found, keep_identity=options.keep_identity)
    unsure = is_uncertain(found, guessed)
    if unsure:
        flog("muted", f"Bizonytalan találat, nézd meg a forrást: {path.name}")
    prefix = "PRÓBA" if options.dry_run else "ÍRVA"
    stage("write")
    try:
        await asyncio.to_thread(write_tags, path, final, options.dry_run, options.embed_cover)
    except Exception as exc:
        stats.failed += 1
        flog("err", f"Tag írás hiba ({path.name}): {exc}")
        _push_file(stats, path.name, "failed", final, found, lines, unsure=True, source_url=url, source_label=label)
        _emit(track, _file_key(path), path.name, "failed", "Hiba", url, label)
        return
    stats.ok += 1
    flog("ok", f"{prefix}: {path.name} → {_line(final)}")
    try:
        from music_id_tagger.rekordbox import path_key

        stats.by_path[path_key(path)] = final
    except OSError:
        pass
    state = "unsure" if unsure else "ok"
    _push_file(stats, path.name, "ok", final, found, lines, unsure=unsure, source_url=url, source_label=label)
    _emit(track, _file_key(path), path.name, state, _line(final), url, label)


async def _sleep(seconds: float, cancel) -> None:
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if cancel.is_set():
            return
        await asyncio.sleep(min(0.2, max(0.0, end - time.monotonic())))
