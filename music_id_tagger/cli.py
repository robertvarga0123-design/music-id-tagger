from __future__ import annotations

import argparse
import threading

from music_id_tagger.engine import Options, run


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Shazam hangminta + Beatport v4 tagger. A jelszót sehova nem menti."
    )
    parser.add_argument("paths", nargs="+", help="Mappák vagy fájlok")
    parser.add_argument("--beatport-user", default="", help="Beatport felhasználónév")
    parser.add_argument("--beatport-pass", default="", help="Beatport jelszó, csak erre a futásra")
    parser.add_argument("--acoustid-key", default="", help="Opcionális AcoustID kulcs")
    parser.add_argument("--spotify-id", default="", help="Spotify Client ID")
    parser.add_argument("--spotify-secret", default="", help="Spotify Client Secret, csak erre a futásra")
    parser.add_argument("--no-spotify", action="store_true")
    parser.add_argument("--no-shazam", action="store_true")
    parser.add_argument("--no-beatport", action="store_true")
    parser.add_argument("--write", action="store_true", help="Tényleg írja a tageket. Enélkül csak próba.")
    parser.add_argument("--overwrite-identity", action="store_true", help="A meglévő címet és előadót is cseréli")
    parser.add_argument("--no-cover", action="store_true")
    parser.add_argument("--delay", type=float, default=1.0)
    args = parser.parse_args(argv)

    options = Options(
        use_shazam=not args.no_shazam,
        use_beatport=not args.no_beatport,
        beatport_user=args.beatport_user,
        beatport_password=args.beatport_pass,
        use_spotify=not args.no_spotify and bool(args.spotify_id and args.spotify_secret),
        spotify_client_id=args.spotify_id,
        spotify_client_secret=args.spotify_secret,
        acoustid_key=args.acoustid_key,
        dry_run=not args.write,
        keep_identity=not args.overwrite_identity,
        embed_cover=not args.no_cover,
        delay=args.delay,
    )

    def log(level: str, text: str) -> None:
        print(f"[{level}] {text}", flush=True)

    stats = run(args.paths, options, log, lambda done, total: None, threading.Event())
    return 0 if stats.failed == 0 else 1
