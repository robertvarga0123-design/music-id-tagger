from __future__ import annotations

import math
from pathlib import Path
from typing import Any

from music_id_tagger.match import clean

AUDIO_EXTENSIONS = {".mp3", ".flac", ".wav", ".aiff", ".aif", ".m4a", ".mp4", ".ogg", ".opus"}

# Pioneer CDJ and Rekordbox read ID3 v2.3 more reliably than v2.4.
ID3_V2_VERSION = 3
COMMENT_MARKER = "[MusicIDTagger]"
SNAPSHOT_KEYS = ("title", "artist", "album", "genre", "year", "bpm", "key", "label", "comment", "isrc")


def _first(value: Any) -> str:
    if isinstance(value, (list, tuple)):
        return clean(value[0]) if value else ""
    return clean(value)


def parse_bpm(value: Any) -> int | None:
    """Whole BPM. Accepts 128, '128.5' and '128,00'. Invalid values are None.

    Half-up rounding: 128.5 becomes 129.
    """
    text = clean(value).replace(",", ".")
    if not text:
        return None
    try:
        number = float(text)
    except ValueError:
        return None
    if not math.isfinite(number) or number <= 0 or number > 400:
        return None
    return int(number + 0.5)


def merge_comment(existing: str, ours: str) -> str:
    """Replace a previous Music ID Tagger note. Keep the listener's own text."""
    text = clean(existing)
    if COMMENT_MARKER in text:
        text = clean(text.split(COMMENT_MARKER, 1)[0].rstrip(" |"))
    if not ours:
        return text
    stamped = f"{COMMENT_MARKER} {ours}"
    if not text:
        return stamped
    return f"{text} | {stamped}"


def read_tags(path: Path) -> dict[str, Any]:
    ext = path.suffix.lower()
    try:
        if ext == ".mp3":
            from mutagen.easyid3 import EasyID3
            from mutagen.id3 import ID3NoHeaderError

            try:
                audio = EasyID3(path)
            except ID3NoHeaderError:
                return {}
            key = ""
            try:
                from mutagen.id3 import ID3

                id3 = ID3(path)
                key = _first(id3.get("TKEY").text) if id3.get("TKEY") else ""
            except Exception:
                key = ""
            return _pack(audio, key)
        if ext == ".flac":
            from mutagen.flac import FLAC

            return _pack(FLAC(path), "")
        if ext in {".m4a", ".mp4"}:
            from mutagen.mp4 import MP4

            audio = MP4(path)
            return {
                "title": _first(audio.get("\xa9nam")),
                "artist": _first(audio.get("\xa9ART")),
                "album": _first(audio.get("\xa9alb")),
                "genre": _first(audio.get("\xa9gen")),
                "year": _first(audio.get("\xa9day"))[:4],
                "bpm": _first(audio.get("tmpo")),
                "key": "",
            }
        if ext == ".ogg":
            from mutagen.oggvorbis import OggVorbis

            return _pack(OggVorbis(path), "")
        if ext == ".opus":
            from mutagen.oggopus import OggOpus

            return _pack(OggOpus(path), "")
        if ext == ".wav":
            from mutagen.wave import WAVE

            return _from_id3(WAVE(path).tags)
        if ext in {".aiff", ".aif"}:
            from mutagen.aiff import AIFF

            return _from_id3(AIFF(path).tags)
    except Exception:
        return {}
    return {}


def _pack(audio: Any, key: str) -> dict[str, Any]:
    year = _first(audio.get("date"))[:4]
    bpm = _first(audio.get("bpm"))
    stored_key = key or _first(audio.get("initialkey") or audio.get("key"))
    return {
        "title": _first(audio.get("title")),
        "artist": _first(audio.get("artist")),
        "album": _first(audio.get("album")),
        "genre": _first(audio.get("genre")),
        "year": year,
        "bpm": bpm,
        "key": stored_key,
        "label": _first(audio.get("label") or audio.get("organization")),
    }


def _from_id3(tags: Any) -> dict[str, Any]:
    if not tags:
        return {}

    def text(frame: str) -> str:
        item = tags.get(frame)
        if not item:
            return ""
        return _first(getattr(item, "text", ""))

    return {
        "title": text("TIT2"),
        "artist": text("TPE1"),
        "album": text("TALB"),
        "genre": text("TCON"),
        "year": (text("TDRC") or text("TYER"))[:4],
        "bpm": text("TBPM"),
        "key": text("TKEY"),
        "label": text("TPUB"),
    }


def read_duration(path: Path) -> float | None:
    """Decoded length in seconds. None when the file does not say."""
    try:
        from mutagen import File

        audio = File(path)
        length = getattr(getattr(audio, "info", None), "length", None)
        if length and float(length) > 1:
            return float(length)
    except Exception:
        return None
    return None


def read_cover_bytes(path: Path) -> bytes | None:
    """Embedded front cover, if the file already has one."""
    ext = path.suffix.lower()
    try:
        if ext == ".mp3":
            from mutagen.id3 import ID3, ID3NoHeaderError

            try:
                return _apic_bytes(ID3(path))
            except ID3NoHeaderError:
                return None
        if ext == ".flac":
            from mutagen.flac import FLAC

            return _picture_bytes(FLAC(path))
        if ext in {".m4a", ".mp4"}:
            from mutagen.mp4 import MP4

            covers = MP4(path).get("covr") or []
            if covers:
                return bytes(covers[0])
        if ext == ".ogg":
            from mutagen.oggvorbis import OggVorbis

            return _picture_bytes(OggVorbis(path))
        if ext == ".opus":
            from mutagen.oggopus import OggOpus

            return _picture_bytes(OggOpus(path))
        if ext == ".wav":
            from mutagen.wave import WAVE

            return _apic_bytes(WAVE(path).tags)
        if ext in {".aiff", ".aif"}:
            from mutagen.aiff import AIFF

            return _apic_bytes(AIFF(path).tags)
    except Exception:
        return None
    return None


def _apic_bytes(tags: Any) -> bytes | None:
    if not tags:
        return None
    fallback = None
    for key in tags.keys():
        if not str(key).startswith("APIC"):
            continue
        frame = tags.get(key)
        data = getattr(frame, "data", None)
        if not data:
            continue
        blob = bytes(data)
        if getattr(frame, "type", None) == 3:
            return blob
        if fallback is None:
            fallback = blob
    return fallback


def _picture_bytes(audio: Any) -> bytes | None:
    pictures = getattr(audio, "pictures", None) or []
    for picture in pictures:
        data = getattr(picture, "data", None)
        if data:
            return bytes(data)
    return None


def _comment(meta: dict[str, Any]) -> str:
    parts = []
    if meta.get("beatport_id"):
        parts.append(f"Beatport ID: {meta['beatport_id']}")
    if meta.get("key_name") and clean(meta.get("key")) and meta["key_name"] != meta["key"]:
        parts.append(f"Key: {meta['key_name']}")
    elif meta.get("key_name") and not meta.get("key"):
        parts.append(f"Key: {meta['key_name']}")
    if meta.get("mix"):
        parts.append(f"Mix: {meta['mix']}")
    if meta.get("catalog"):
        parts.append(f"Cat: {meta['catalog']}")
    if meta.get("mbid"):
        parts.append(f"MBID: {meta['mbid']}")
    if meta.get("spotify_id"):
        parts.append(f"Spotify: {meta['spotify_id']}")
    if meta.get("source"):
        parts.append(f"Source: {meta['source']}")
    return " | ".join(parts)


def snapshot_tags(path: Path) -> dict[str, str]:
    """Fields an undo entry can restore. Cover art is intentionally absent."""
    found = read_tags(path)
    found["comment"] = _read_comment(path)
    found["isrc"] = found.get("isrc") or _read_isrc(path)
    return {key: clean(found.get(key)) for key in SNAPSHOT_KEYS}


def _read_comment(path: Path) -> str:
    ext = path.suffix.lower()
    try:
        if ext == ".mp3":
            from mutagen.id3 import ID3, ID3NoHeaderError

            try:
                tags = ID3(path)
            except ID3NoHeaderError:
                return ""
            return _id3_comment(tags)
        if ext == ".flac":
            from mutagen.flac import FLAC

            return _first(FLAC(path).get("comment"))
        if ext == ".ogg":
            from mutagen.oggvorbis import OggVorbis

            return _first(OggVorbis(path).get("comment"))
        if ext == ".opus":
            from mutagen.oggopus import OggOpus

            return _first(OggOpus(path).get("comment"))
        if ext in {".m4a", ".mp4"}:
            from mutagen.mp4 import MP4

            return _first(MP4(path).get("\xa9cmt"))
        if ext == ".wav":
            from mutagen.wave import WAVE

            return _id3_comment(WAVE(path).tags)
        if ext in {".aiff", ".aif"}:
            from mutagen.aiff import AIFF

            return _id3_comment(AIFF(path).tags)
    except Exception:
        return ""
    return ""


def _id3_comment(tags: Any) -> str:
    if not tags:
        return ""
    texts = []
    for key in tags.keys():
        if not str(key).startswith("COMM"):
            continue
        frame = tags.get(key)
        text = _first(getattr(frame, "text", ""))
        if text:
            texts.append(text)
    return " | ".join(texts)


def _read_isrc(path: Path) -> str:
    ext = path.suffix.lower()
    try:
        if ext == ".mp3":
            from mutagen.id3 import ID3, ID3NoHeaderError

            try:
                tags = ID3(path)
            except ID3NoHeaderError:
                return ""
            return _first(getattr(tags.get("TSRC"), "text", ""))
        if ext == ".flac":
            from mutagen.flac import FLAC

            return _first(FLAC(path).get("isrc"))
        if ext in {".m4a", ".mp4"}:
            from mutagen.mp4 import MP4, MP4FreeForm

            audio = MP4(path)
            raw = audio.get("----:com.apple.iTunes:ISRC")
            if not raw:
                return ""
            item = raw[0]
            if isinstance(item, MP4FreeForm):
                return clean(bytes(item).decode("utf-8", "replace"))
            return clean(item)
    except Exception:
        return ""
    return ""


def _download_cover(url: str) -> tuple[bytes, str] | None:
    if not url:
        return None
    import requests

    response = requests.get(url, timeout=20)
    if response.status_code != 200 or not response.content or len(response.content) > 5_000_000:
        return None
    mime = response.headers.get("Content-Type", "image/jpeg").split(";")[0].strip() or "image/jpeg"
    if not mime.startswith("image/"):
        mime = "image/jpeg"
    return response.content, mime


def changed_fields(before: dict, after: dict) -> dict:
    """Tag fields whose value actually differs. Unchanged BPM is not rewritten."""
    source = before or {}
    incoming = after or {}
    out: dict = {}
    for key in ("title", "artist", "album", "genre", "year", "bpm", "key", "label", "isrc", "beatport_id"):
        value = incoming.get(key)
        if value in (None, ""):
            continue
        if clean(value) != clean(source.get(key)):
            out[key] = value
    return out


def write_tags(path: Path, meta: dict[str, Any], dry_run: bool, embed_cover: bool) -> None:
    if dry_run:
        return
    before = snapshot_tags(path)
    delta = changed_fields(read_tags(path), meta)
    ext = path.suffix.lower()
    comment = _comment(meta)
    cover = _download_cover(meta.get("cover_url") or "") if embed_cover and meta.get("cover_url") else None
    if ext == ".mp3":
        _write_mp3(path, delta, comment, cover)
    elif ext == ".flac":
        _write_vorbis(path, delta, comment, cover, "flac")
    elif ext == ".ogg":
        _write_vorbis(path, delta, comment, cover, "ogg")
    elif ext == ".opus":
        _write_vorbis(path, delta, comment, cover, "opus")
    elif ext in {".m4a", ".mp4"}:
        _write_mp4(path, delta, comment, cover)
    elif ext == ".wav":
        _write_id3_audio(path, delta, comment, cover, "wav")
    elif ext in {".aiff", ".aif"}:
        _write_id3_audio(path, delta, comment, cover, "aiff")
    else:
        raise ValueError(f"Nem támogatott formátum: {ext}")
    from music_id_tagger.undo import record

    record(path, before, snapshot_tags(path))


def _assign_easy(audio: Any, meta: dict[str, Any]) -> None:
    if meta.get("title"):
        audio["title"] = str(meta["title"])
    if meta.get("artist"):
        audio["artist"] = str(meta["artist"])
    if meta.get("album"):
        audio["album"] = str(meta["album"])
    if meta.get("genre"):
        audio["genre"] = str(meta["genre"])
    if meta.get("year"):
        audio["date"] = str(meta["year"])
    if meta.get("bpm"):
        bpm = parse_bpm(meta.get("bpm"))
        if bpm is not None:
            audio["bpm"] = str(bpm)


def _replace_comment_id3(id3, comment: str) -> None:
    for key in list(id3.keys()):
        frame = id3.get(key)
        if str(key).startswith("COMM") and getattr(frame, "desc", "") == "MusicIDTagger":
            del id3[key]
    if comment:
        from mutagen.id3 import COMM

        id3.add(COMM(encoding=3, lang="eng", desc="MusicIDTagger", text=comment))


def _restore_id3_comment(id3, text: str) -> None:
    """A látható kommentet állítja vissza. A külön COMM keretek egy szöveggé olvadnak."""
    from mutagen.id3 import COMM

    for key in list(id3.keys()):
        if str(key).startswith("COMM"):
            del id3[key]
    if text:
        id3.add(COMM(encoding=3, lang="eng", desc="", text=text))


def _set_vorbis_comment(audio: Any, comment: str, previous: str) -> None:
    merged = merge_comment(previous, comment)
    if merged:
        audio["comment"] = merged
    elif "comment" in audio:
        del audio["comment"]


def _write_mp3(path: Path, meta: dict[str, Any], comment: str, cover: tuple[bytes, str] | None) -> None:
    from mutagen.easyid3 import EasyID3
    from mutagen.id3 import APIC, ID3, TKEY, TPUB, TSRC
    from mutagen.mp3 import MP3

    audio = MP3(path, ID3=EasyID3)
    if audio.tags is None:
        audio.add_tags()
    _assign_easy(audio, meta)
    audio.save(v2_version=ID3_V2_VERSION)

    id3 = ID3(path)
    if meta.get("key"):
        id3.delall("TKEY")
        id3.add(TKEY(encoding=3, text=str(meta["key"])))
    if meta.get("label"):
        id3.delall("TPUB")
        id3.add(TPUB(encoding=3, text=str(meta["label"])))
    if meta.get("isrc"):
        id3.delall("TSRC")
        id3.add(TSRC(encoding=3, text=str(meta["isrc"])))
    _replace_comment_id3(id3, comment)
    if cover and not any(str(key).startswith("APIC") for key in id3.keys()):
        id3.add(APIC(encoding=3, mime=cover[1], type=3, desc="Cover", data=cover[0]))
    id3.save(v2_version=ID3_V2_VERSION)


def _write_vorbis(path: Path, meta: dict[str, Any], comment: str, cover: tuple[bytes, str] | None, kind: str) -> None:
    if kind == "flac":
        from mutagen.flac import FLAC, Picture

        audio = FLAC(path)
    elif kind == "opus":
        from mutagen.oggopus import OggOpus

        audio = OggOpus(path)
        Picture = None
    else:
        from mutagen.oggvorbis import OggVorbis

        audio = OggVorbis(path)
        Picture = None
    _assign_easy(audio, meta)
    if meta.get("key"):
        audio["initialkey"] = str(meta["key"])
    if meta.get("label"):
        audio["label"] = str(meta["label"])
    if meta.get("isrc"):
        audio["isrc"] = str(meta["isrc"])
    if meta.get("beatport_id"):
        audio["beatport_trackid"] = str(meta["beatport_id"])
    _set_vorbis_comment(audio, comment, _first(audio.get("comment")))
    if kind == "flac" and cover and Picture is not None and not getattr(audio, "pictures", None):
        picture = Picture()
        picture.type = 3
        picture.mime = cover[1]
        picture.data = cover[0]
        audio.add_picture(picture)
    audio.save()


def _write_mp4(path: Path, meta: dict[str, Any], comment: str, cover: tuple[bytes, str] | None) -> None:
    from mutagen.mp4 import MP4, MP4Cover, MP4FreeForm

    audio = MP4(path)
    if meta.get("title"):
        audio["\xa9nam"] = [str(meta["title"])]
    if meta.get("artist"):
        audio["\xa9ART"] = [str(meta["artist"])]
    if meta.get("album"):
        audio["\xa9alb"] = [str(meta["album"])]
    if meta.get("genre"):
        audio["\xa9gen"] = [str(meta["genre"])]
    if meta.get("year"):
        audio["\xa9day"] = [str(meta["year"])]
    if meta.get("bpm"):
        bpm = parse_bpm(meta.get("bpm"))
        if bpm is not None:
            audio["tmpo"] = [bpm]
    if meta.get("key"):
        audio["----:com.apple.iTunes:initialkey"] = [MP4FreeForm(str(meta["key"]).encode("utf-8"))]
    if meta.get("label"):
        audio["----:com.apple.iTunes:LABEL"] = [MP4FreeForm(str(meta["label"]).encode("utf-8"))]
    if meta.get("beatport_id"):
        audio["----:com.apple.iTunes:BeatportID"] = [MP4FreeForm(str(meta["beatport_id"]).encode("utf-8"))]
    if comment or audio.get("\xa9cmt"):
        merged = merge_comment(_first(audio.get("\xa9cmt")), comment)
        if merged:
            audio["\xa9cmt"] = [merged]
        elif "\xa9cmt" in audio:
            del audio["\xa9cmt"]
    if cover and "covr" not in audio:
        fmt = MP4Cover.FORMAT_PNG if "png" in cover[1] else MP4Cover.FORMAT_JPEG
        audio["covr"] = [MP4Cover(cover[0], imageformat=fmt)]
    audio.save()


def _write_id3_audio(path: Path, meta: dict[str, Any], comment: str, cover: tuple[bytes, str] | None, kind: str) -> None:
    from mutagen.id3 import APIC, TALB, TBPM, TCON, TDRC, TIT2, TKEY, TPE1, TPUB, TSRC

    if kind == "wav":
        from mutagen.wave import WAVE

        audio = WAVE(path)
    else:
        from mutagen.aiff import AIFF

        audio = AIFF(path)
    if audio.tags is None:
        audio.add_tags()
    id3 = audio.tags
    frames = {
        "TIT2": (TIT2, meta.get("title")),
        "TPE1": (TPE1, meta.get("artist")),
        "TALB": (TALB, meta.get("album")),
        "TCON": (TCON, meta.get("genre")),
        "TDRC": (TDRC, meta.get("year")),
        "TBPM": (TBPM, str(parse_bpm(meta.get("bpm")) or "") if meta.get("bpm") else None),
    }
    for frame, (cls, value) in frames.items():
        if value:
            id3.delall(frame)
            id3.add(cls(encoding=3, text=str(value)))
    if meta.get("key"):
        id3.delall("TKEY")
        id3.add(TKEY(encoding=3, text=str(meta["key"])))
    if meta.get("label"):
        id3.delall("TPUB")
        id3.add(TPUB(encoding=3, text=str(meta["label"])))
    if meta.get("isrc"):
        id3.delall("TSRC")
        id3.add(TSRC(encoding=3, text=str(meta["isrc"])))
    _replace_comment_id3(id3, comment)
    if cover and not any(str(key).startswith("APIC") for key in id3.keys()):
        id3.add(APIC(encoding=3, mime=cover[1], type=3, desc="Cover", data=cover[0]))
    audio.save(v2_version=ID3_V2_VERSION)


def restore_tags(path: Path, fields: dict[str, str]) -> None:
    """Put selected fields back. Empty string deletes that field. Cover art stays."""
    ext = path.suffix.lower()
    if ext == ".mp3":
        _restore_mp3(path, fields)
    elif ext == ".flac":
        _restore_vorbis(path, fields, "flac")
    elif ext == ".ogg":
        _restore_vorbis(path, fields, "ogg")
    elif ext == ".opus":
        _restore_vorbis(path, fields, "opus")
    elif ext in {".m4a", ".mp4"}:
        _restore_mp4(path, fields)
    elif ext == ".wav":
        _restore_id3_audio(path, fields, "wav")
    elif ext in {".aiff", ".aif"}:
        _restore_id3_audio(path, fields, "aiff")
    else:
        raise ValueError(f"Nem támogatott formátum: {ext}")


def _put(audio: Any, key: str, value: str) -> None:
    if value:
        audio[key] = value
    elif key in audio:
        del audio[key]


def _restore_mp3(path: Path, fields: dict[str, str]) -> None:
    from mutagen.easyid3 import EasyID3
    from mutagen.id3 import ID3, TKEY, TPUB, TSRC
    from mutagen.mp3 import MP3

    audio = MP3(path, ID3=EasyID3)
    if audio.tags is None:
        audio.add_tags()
    for easy, key in (
        ("title", "title"),
        ("artist", "artist"),
        ("album", "album"),
        ("genre", "genre"),
        ("date", "year"),
        ("bpm", "bpm"),
    ):
        if key in fields:
            _put(audio, easy, fields[key])
    audio.save(v2_version=ID3_V2_VERSION)
    id3 = ID3(path)
    if "key" in fields:
        id3.delall("TKEY")
        if fields["key"]:
            id3.add(TKEY(encoding=3, text=fields["key"]))
    if "label" in fields:
        id3.delall("TPUB")
        if fields["label"]:
            id3.add(TPUB(encoding=3, text=fields["label"]))
    if "isrc" in fields:
        id3.delall("TSRC")
        if fields["isrc"]:
            id3.add(TSRC(encoding=3, text=fields["isrc"]))
    if "comment" in fields:
        _restore_id3_comment(id3, fields["comment"])
    id3.save(v2_version=ID3_V2_VERSION)


def _restore_vorbis(path: Path, fields: dict[str, str], kind: str) -> None:
    if kind == "flac":
        from mutagen.flac import FLAC

        audio = FLAC(path)
    elif kind == "opus":
        from mutagen.oggopus import OggOpus

        audio = OggOpus(path)
    else:
        from mutagen.oggvorbis import OggVorbis

        audio = OggVorbis(path)
    mapping = {
        "title": "title",
        "artist": "artist",
        "album": "album",
        "genre": "genre",
        "year": "date",
        "bpm": "bpm",
        "key": "initialkey",
        "label": "label",
        "isrc": "isrc",
        "comment": "comment",
    }
    for key, tag in mapping.items():
        if key in fields:
            _put(audio, tag, fields[key])
    audio.save()


def _restore_mp4(path: Path, fields: dict[str, str]) -> None:
    from mutagen.mp4 import MP4

    audio = MP4(path)
    mapping = {
        "title": "\xa9nam",
        "artist": "\xa9ART",
        "album": "\xa9alb",
        "genre": "\xa9gen",
        "year": "\xa9day",
        "comment": "\xa9cmt",
    }
    for key, tag in mapping.items():
        if key not in fields:
            continue
        if fields[key]:
            audio[tag] = [fields[key]]
        elif tag in audio:
            del audio[tag]
    if "bpm" in fields:
        bpm = parse_bpm(fields["bpm"])
        if bpm is None and "tmpo" in audio:
            del audio["tmpo"]
        elif bpm is not None:
            audio["tmpo"] = [bpm]
    audio.save()


def _restore_id3_audio(path: Path, fields: dict[str, str], kind: str) -> None:
    from mutagen.id3 import TALB, TBPM, TCON, TDRC, TIT2, TKEY, TPE1, TPUB, TSRC

    if kind == "wav":
        from mutagen.wave import WAVE

        audio = WAVE(path)
    else:
        from mutagen.aiff import AIFF

        audio = AIFF(path)
    if audio.tags is None:
        audio.add_tags()
    id3 = audio.tags
    frames = {
        "title": ("TIT2", TIT2),
        "artist": ("TPE1", TPE1),
        "album": ("TALB", TALB),
        "genre": ("TCON", TCON),
        "year": ("TDRC", TDRC),
        "bpm": ("TBPM", TBPM),
        "key": ("TKEY", TKEY),
        "label": ("TPUB", TPUB),
        "isrc": ("TSRC", TSRC),
    }
    for key, (frame, cls) in frames.items():
        if key not in fields:
            continue
        id3.delall(frame)
        if fields[key]:
            id3.add(cls(encoding=3, text=fields[key]))
    if "comment" in fields:
        _restore_id3_comment(id3, fields["comment"])
    audio.save(v2_version=ID3_V2_VERSION)
