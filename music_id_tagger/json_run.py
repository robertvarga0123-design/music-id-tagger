"""stdin JSON -> result file. Credentials stay in this process and are not logged."""

from __future__ import annotations

import json
import sys
import traceback
from dataclasses import asdict
from pathlib import Path

from music_id_tagger.engine import Options, run


class _Cancel:
    def is_set(self) -> bool:
        return False


def _bool(value: object, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"1", "true", "yes", "on"}:
            return True
        if lowered in {"0", "false", "no", "off"}:
            return False
    return default


def _id_map(value: object) -> dict[str, str]:
    from music_id_tagger.beatport import parse_beatport_id

    if not isinstance(value, dict):
        return {}
    found: dict[str, str] = {}
    for key, item in value.items():
        if not isinstance(key, str):
            continue
        ident = parse_beatport_id(item)
        if ident:
            found[key] = ident
    return found


def _text(value: object) -> str:
    return value if isinstance(value, str) else ""


def _write(path: Path, payload: dict) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def main() -> int:
    if len(sys.argv) != 2:
        print("missing result path", file=sys.stderr)
        return 2
    out = Path(sys.argv[1])
    try:
        payload = json.load(sys.stdin)
        if not isinstance(payload, dict):
            raise ValueError("payload")
        raw_paths = payload.get("paths")
        paths = [item for item in raw_paths if isinstance(item, str)] if isinstance(raw_paths, list) else []
        raw = payload.get("options") if isinstance(payload.get("options"), dict) else {}
        options = Options(
            use_shazam=_bool(raw.get("use_shazam"), True),
            use_beatport=_bool(raw.get("use_beatport"), True),
            beatport_user=_text(raw.get("beatport_user")).strip(),
            beatport_password=_text(raw.get("beatport_password")),
            use_spotify=_bool(raw.get("use_spotify"), False),
            spotify_client_id=_text(raw.get("spotify_client_id")).strip(),
            spotify_client_secret=_text(raw.get("spotify_client_secret")),
            acoustid_key="",
            dry_run=_bool(raw.get("dry_run"), True),
            keep_identity=_bool(raw.get("keep_identity"), True),
            embed_cover=_bool(raw.get("embed_cover"), True),
            delay=0.25,
            beatport_by_file=_id_map(raw.get("beatport_by_file")),
            use_open_catalogs=_bool(raw.get("use_open_catalogs"), True),
            use_deezer=_bool(raw.get("use_deezer"), True),
            use_apple=_bool(raw.get("use_apple"), True),
            use_musicbrainz=_bool(raw.get("use_musicbrainz"), True),
            use_discogs=_bool(raw.get("use_discogs"), True),
            use_websearch=_bool(raw.get("use_websearch"), False),
            defer_write=True,
            rescan=_bool(raw.get("rescan"), False),
            fill_missing_only=_bool(raw.get("fill_missing_only"), False),
            tag_first=_bool(raw.get("tag_first"), False),
            key_format=_text(raw.get("key_format")) or "camelot",
            rename_template=_text(raw.get("rename_template")),
            enabled_fields=raw.get("enabled_fields") if isinstance(raw.get("enabled_fields"), dict) else {},
            genre_map=raw.get("genre_map") if isinstance(raw.get("genre_map"), dict) else {},
        )
        logs: list[dict[str, str]] = []

        def log(level: str, message: str) -> None:
            logs.append({"level": level, "message": message})

        stats = run(paths, options, log, lambda _done, _total: None, _Cancel())
        applied = 0
        if not options.dry_run:
            from music_id_tagger.pending import apply_pending, select_for_apply

            applied = apply_pending(select_for_apply(list(stats.pending), "all"), options, log, list(stats.xmls))
        _write(
            out,
            {
                "total": stats.total,
                "ok": stats.ok,
                "missed": stats.missed,
                "failed": stats.failed,
                "cancelled": stats.cancelled,
                "dry_run": options.dry_run,
                "applied": applied,
                "log": logs,
                "files": [asdict(item) for item in stats.files],
            },
        )
        return 0
    except Exception:
        traceback.print_exc(file=sys.stderr)
        try:
            _write(out, {"error": "A felismerés közben hiba történt."})
        except Exception:
            traceback.print_exc(file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
