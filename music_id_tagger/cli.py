from __future__ import annotations

import argparse
import threading

from music_id_tagger.engine import Options, run


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Shazam hangminta + Beatport v4 tagger. A jelszót sehova nem menti."
    )
    parser.add_argument("paths", nargs="*", help="Mappák vagy fájlok")
    parser.add_argument("--undo", default="", help="Egy undo JSON visszaállítása")
    parser.add_argument("--beatport-user", default="", help="Beatport felhasználónév")
    parser.add_argument("--beatport-pass", default="", help="Beatport jelszó, csak erre a futásra")
    parser.add_argument("--acoustid-key", default="", help="Opcionális AcoustID kulcs")
    parser.add_argument("--spotify-id", default="", help="Spotify Client ID")
    parser.add_argument("--spotify-secret", default="", help="Spotify Client Secret, csak erre a futásra")
    parser.add_argument("--grok-key", default="", help="xAI Grok API kulcs, csak erre a futásra")
    parser.add_argument("--gemini-key", default="", help="Google Gemini API kulcs, csak erre a futásra")
    parser.add_argument("--no-spotify", action="store_true")
    parser.add_argument("--no-shazam", action="store_true")
    parser.add_argument("--no-beatport", action="store_true")
    parser.add_argument("--write", action="store_true", help="Tényleg írja a tageket. Enélkül csak próba.")
    parser.add_argument("--overwrite-identity", action="store_true", help="A meglévő címet és előadót is cseréli")
    parser.add_argument("--no-cover", action="store_true")
    parser.add_argument("--no-xml-bpm", action="store_true", help="A Rekordbox XML BPM mezőit nem írja")
    parser.add_argument("--no-catalogs", action="store_true", help="Deezer, Apple és MusicBrainz kihagyása")
    parser.add_argument("--delay", type=float, default=1.0)
    args = parser.parse_args(argv)

    def log(level: str, text: str) -> None:
        print(f"[{level}] {text}", flush=True)

    if args.undo:
        from pathlib import Path

        from music_id_tagger.undo import revert

        def confirm(path: Path) -> bool:
            answer = input(f"{path} megváltozott a címkézés óta. Visszaállítsam? [i/n] ")
            return answer.strip().lower() in {"i", "igen", "y", "yes"}

        revert(Path(args.undo), log, confirm)
        return 0
    if not args.paths:
        parser.error("adj meg legalább egy mappát vagy fájlt")

    options = Options(
        use_shazam=not args.no_shazam,
        use_beatport=not args.no_beatport,
        beatport_user=args.beatport_user,
        beatport_password=args.beatport_pass,
        use_spotify=not args.no_spotify and bool(args.spotify_id and args.spotify_secret),
        spotify_client_id=args.spotify_id,
        spotify_client_secret=args.spotify_secret,
        acoustid_key=args.acoustid_key,
        grok_key=args.grok_key,
        gemini_key=args.gemini_key,
        dry_run=not args.write,
        keep_identity=not args.overwrite_identity,
        embed_cover=not args.no_cover,
        delay=args.delay,
        write_bpm_to_xml=not args.no_xml_bpm,
        use_open_catalogs=not args.no_catalogs,
    )

    stats = run(args.paths, options, log, lambda done, total: None, threading.Event())
    return 0 if stats.failed == 0 else 1
