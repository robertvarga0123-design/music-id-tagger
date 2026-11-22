from __future__ import annotations

from pathlib import Path
from typing import Any

from music_id_tagger.match import clean

AUDIO_EXTENSIONS = {".mp3", ".flac", ".wav", ".aiff", ".aif", ".m4a", ".mp4", ".ogg", ".opus"}


def _first(value: Any) -> str:
    if isinstance(value, (list, tuple)):
        return clean(value[0]) if value else ""
    return clean(value)


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


def write_tags(path: Path, meta: dict[str, Any], dry_run: bool, embed_cover: bool) -> None:
    if dry_run:
        return
    ext = path.suffix.lower()
    comment = _comment(meta)
    cover = _download_cover(meta.get("cover_url") or "") if embed_cover and meta.get("cover_url") else None
    if ext == ".mp3":
        _write_mp3(path, meta, comment, cover)
    elif ext == ".flac":
        _write_vorbis(path, meta, comment, cover, "flac")
    elif ext == ".ogg":
        _write_vorbis(path, meta, comment, cover, "ogg")
    elif ext == ".opus":
        _write_vorbis(path, meta, comment, cover, "opus")
    elif ext in {".m4a", ".mp4"}:
        _write_mp4(path, meta, comment, cover)
    elif ext == ".wav":
        _write_id3_audio(path, meta, comment, cover, "wav")
    elif ext in {".aiff", ".aif"}:
        _write_id3_audio(path, meta, comment, cover, "aiff")
    else:
        raise ValueError(f"Nem támogatott formátum: {ext}")


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
        audio["bpm"] = str(int(meta["bpm"]))


def _replace_comment_id3(id3, comment: str) -> None:
    for key in list(id3.keys()):
        frame = id3.get(key)
        if str(key).startswith("COMM") and getattr(frame, "desc", "") == "MusicIDTagger":
            del id3[key]
    if comment:
        from mutagen.id3 import COMM

        id3.add(COMM(encoding=3, lang="eng", desc="MusicIDTagger", text=comment))


def _set_vorbis_comment(audio: Any, comment: str) -> None:
    if not comment:
        return
    current = ""
    if audio.get("comment"):
        current = str(audio.get("comment")[0])
    if not current:
        audio["comment"] = comment
    elif "Beatport ID:" in current:
        audio["comment"] = comment
    else:
        audio["comment"] = current + " | " + comment


def _write_mp3(path: Path, meta: dict[str, Any], comment: str, cover: tuple[bytes, str] | None) -> None:
    from mutagen.easyid3 import EasyID3
    from mutagen.id3 import APIC, ID3, TKEY, TPUB, TSRC
    from mutagen.mp3 import MP3

    audio = MP3(path, ID3=EasyID3)
    if audio.tags is None:
        audio.add_tags()
    _assign_easy(audio, meta)
    audio.save()

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
    id3.save()


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
    _set_vorbis_comment(audio, comment)
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
        audio["tmpo"] = [int(meta["bpm"])]
    if meta.get("key"):
        audio["----:com.apple.iTunes:initialkey"] = [MP4FreeForm(str(meta["key"]).encode("utf-8"))]
    if meta.get("label"):
        audio["----:com.apple.iTunes:LABEL"] = [MP4FreeForm(str(meta["label"]).encode("utf-8"))]
    if meta.get("beatport_id"):
        audio["----:com.apple.iTunes:BeatportID"] = [MP4FreeForm(str(meta["beatport_id"]).encode("utf-8"))]
    if comment:
        audio["\xa9cmt"] = [comment]
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
        "TBPM": (TBPM, str(int(meta["bpm"])) if meta.get("bpm") else None),
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
    audio.save()
