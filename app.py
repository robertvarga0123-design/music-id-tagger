"""PyInstaller belépő. Dupla kattintásra a magyar ablak nyílik."""

from __future__ import annotations

import multiprocessing
import os
import sys
import traceback


def _certs() -> None:
    try:
        import certifi

        os.environ.setdefault("SSL_CERT_FILE", certifi.where())
        os.environ.setdefault("REQUESTS_CA_BUNDLE", certifi.where())
    except Exception:
        pass


def _crash(exc_type, exc, tb) -> None:
    text = "".join(traceback.format_exception(exc_type, exc, tb))
    try:
        from music_id_tagger.config import settings_dir

        folder = settings_dir()
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "crash.log").write_text(text, encoding="utf-8")
    except Exception:
        pass
    try:
        import tkinter as tk
        from tkinter import messagebox

        root = tk.Tk()
        root.withdraw()
        messagebox.showerror(
            "Music ID Tagger",
            "A program hibára futott. A részletek a crash.log fájlban vannak.\n\n" + text[-900:],
        )
        root.destroy()
    except Exception:
        pass


def main() -> None:
    multiprocessing.freeze_support()
    _certs()
    sys.excepthook = _crash
    from music_id_tagger.gui import run_gui

    run_gui()


if __name__ == "__main__":
    main()
