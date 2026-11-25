from __future__ import annotations

import queue
import threading
import tkinter as tk
import webbrowser
from pathlib import Path
from tkinter import filedialog, font as tkfont, messagebox, ttk

from music_id_tagger import __version__
from music_id_tagger.config import load_password, load_settings, load_spotify_secret, save_settings
from music_id_tagger.engine import Options, run

BG = "#10110f"
PAPER = "#1c1d18"
INK = "#f3f0e7"
MUTED = "#a39e90"
BRASS = "#e0a84a"
CLAY = "#d4654a"
ENTRY = "#26271f"
LINE = "#3a3b32"
WARN = "#f2c14e"
LINK = "#9ec1ff"

_STATE = {
    "wait": "Vár",
    "run": "Folyamatban",
    "shazam": "Shazam…",
    "acoustid": "AcoustID…",
    "beatport": "Beatport…",
    "spotify": "Spotify…",
    "deezer": "Deezer…",
    "apple": "Apple…",
    "musicbrainz": "MusicBrainz…",
    "discogs": "Discogs…",
    "web": "Keresés…",
    "write": "Írás…",
    "ok": "Kész",
    "unsure": "! Bizonytalan",
    "missed": "! Nincs találat",
    "failed": "Hiba",
}


class App(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title(f"Music ID Tagger {__version__}")
        self.geometry("980x780")
        self.minsize(860, 680)
        self.configure(bg=BG)
        self.queue: queue.Queue = queue.Queue()
        self.cancel = threading.Event()
        self.worker: threading.Thread | None = None
        self.paths: list[str] = []
        self.beatport_links: dict[str, str] = {}
        self.rows: dict[str, str] = {}
        self.row_paths: dict[str, str] = {}
        self.urls: dict[str, str] = {}
        self._fonts: list[tkfont.Font] = []
        self._build()
        self._load()
        self.after(120, self._drain)
        self.after(1500, lambda: self._check_update(False))
        self.protocol("WM_DELETE_WINDOW", self._close)

    def _face(self, size: int, bold: bool = False) -> tkfont.Font:
        family = "Segoe UI" if self._windows() else "DejaVu Sans"
        item = tkfont.Font(family=family, size=size, weight="bold" if bold else "normal")
        self._fonts.append(item)
        return item

    def _build(self) -> None:
        self.option_add("*Font", str(self._face(10)))
        head = tk.Frame(self, bg=BG)
        head.pack(fill="x", padx=18, pady=(16, 8))
        tk.Label(head, text="Music ID Tagger", bg=BG, fg=BRASS, font=self._face(20, True)).pack(anchor="w")
        tk.Label(
            head,
            text="Hangminta a Shazammal, BPM és stílus a Beatportról. Húzd ide a mappát, a zenét vagy a Rekordbox XML-t.",
            bg=BG,
            fg=MUTED,
        ).pack(anchor="w", pady=(2, 0))

        body = tk.Frame(self, bg=BG)
        body.pack(fill="both", expand=True, padx=18)
        body.columnconfigure(0, weight=3)
        body.columnconfigure(1, weight=2)
        body.rowconfigure(0, weight=1)

        left = tk.Frame(body, bg=PAPER, highlightbackground=LINE, highlightthickness=1)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 8), pady=8)
        right = tk.Frame(body, bg=PAPER, highlightbackground=LINE, highlightthickness=1)
        right.grid(row=0, column=1, sticky="nsew", padx=(8, 0), pady=8)

        tk.Label(left, text="Mappák és fájlok", bg=PAPER, fg=INK, font=self._face(12, True)).pack(
            anchor="w", padx=12, pady=(12, 6)
        )
        tk.Label(
            left,
            text="A szám mellett látszik, hol tart. A sárga ! bizonytalan.",
            bg=PAPER,
            fg=MUTED,
        ).pack(anchor="w", padx=12, pady=(0, 6))
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure(
            "Tracks.Treeview",
            background=ENTRY,
            fieldbackground=ENTRY,
            foreground=INK,
            borderwidth=0,
            rowheight=28,
            font=str(self._face(10)),
        )
        style.configure(
            "Tracks.Treeview.Heading",
            background=PAPER,
            foreground=MUTED,
            relief="flat",
            font=str(self._face(10, True)),
        )
        style.map("Tracks.Treeview", background=[("selected", "#3a3424")], foreground=[("selected", INK)])
        list_wrap = tk.Frame(left, bg=PAPER)
        list_wrap.pack(fill="both", expand=True, padx=12, pady=(0, 8))
        self.tree = ttk.Treeview(
            list_wrap,
            columns=("file", "state", "source"),
            show="headings",
            style="Tracks.Treeview",
        )
        self.tree.heading("file", text="Fájl")
        self.tree.heading("state", text="Hol tart")
        self.tree.heading("source", text="Forrás")
        self.tree.column("file", width=280, stretch=True)
        self.tree.column("state", width=150, stretch=False, anchor="w")
        self.tree.column("source", width=140, stretch=False, anchor="w")
        for name, color in (
            ("ok", INK),
            ("run", BRASS),
            ("shazam", BRASS),
            ("acoustid", BRASS),
            ("beatport", BRASS),
            ("spotify", BRASS),
            ("deezer", BRASS),
            ("apple", BRASS),
            ("musicbrainz", BRASS),
            ("discogs", BRASS),
            ("web", BRASS),
            ("write", BRASS),
            ("wait", MUTED),
            ("unsure", WARN),
            ("missed", WARN),
            ("bad", CLAY),
        ):
            self.tree.tag_configure(name, foreground=color)
        scroll = ttk.Scrollbar(list_wrap, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        self.tree.bind("<ButtonRelease-1>", self._open_source)
        buttons = tk.Frame(left, bg=PAPER)
        buttons.pack(fill="x", padx=12, pady=(0, 12))
        self._button(buttons, "Mappa", self._add_folder, BRASS).pack(side="left", padx=(0, 6))
        self._button(buttons, "Fájlok", self._add_files, BRASS).pack(side="left", padx=(0, 6))
        self._button(buttons, "Kijelölt törlése", self._remove, CLAY).pack(side="left")
        tk.Label(left, text="Beatport link vagy ID a kijelölt fájlhoz", bg=PAPER, fg=MUTED).pack(
            anchor="w", padx=12, pady=(0, 0)
        )
        link_row = tk.Frame(left, bg=PAPER)
        link_row.pack(fill="x", padx=12, pady=(2, 12))
        self.bp_link = tk.Entry(link_row, bg=ENTRY, fg=INK, insertbackground=INK, relief="flat")
        self.bp_link.pack(side="left", fill="x", expand=True, ipady=4)
        self._button(link_row, "ID mentése", self._assign_beatport, BRASS).pack(side="left", padx=(6, 0))

        tk.Label(right, text="Források", bg=PAPER, fg=INK, font=self._face(12, True)).pack(
            anchor="w", padx=12, pady=(12, 6)
        )
        self.use_shazam = tk.BooleanVar(value=True)
        self.use_beatport = tk.BooleanVar(value=True)
        self.use_spotify = tk.BooleanVar(value=True)
        self.use_open_catalogs = tk.BooleanVar(value=True)
        self.dry_run = tk.BooleanVar(value=True)
        self.keep_identity = tk.BooleanVar(value=True)
        self.embed_cover = tk.BooleanVar(value=True)
        self.write_bpm_to_xml = tk.BooleanVar(value=True)
        self._check(right, "Shazam hangminta", self.use_shazam)
        self._check(right, "Beatport (BPM, hangnem, stílus)", self.use_beatport)
        self._check(right, "Deezer, Apple, MusicBrainz, Discogs", self.use_open_catalogs)
        tk.Label(right, text="Beatport felhasználó", bg=PAPER, fg=MUTED).pack(anchor="w", padx=12, pady=(8, 0))
        self.user = self._entry(right)
        tk.Label(right, text="Jelszó  ·  erre a gépre emlékezik", bg=PAPER, fg=MUTED).pack(anchor="w", padx=12, pady=(8, 0))
        self.password = self._entry(right, secret=True)
        self._check(right, "Spotify (album, év, ISRC)", self.use_spotify)
        tk.Label(right, text="Spotify Client ID", bg=PAPER, fg=MUTED).pack(anchor="w", padx=12, pady=(8, 0))
        self.spotify_id = self._entry(right)
        tk.Label(right, text="Spotify Client Secret  ·  erre a gépre emlékezik", bg=PAPER, fg=MUTED).pack(
            anchor="w", padx=12, pady=(8, 0)
        )
        self.spotify_secret = self._entry(right, secret=True)
        tk.Label(right, text="AcoustID kulcs  ·  nem kötelező", bg=PAPER, fg=MUTED).pack(anchor="w", padx=12, pady=(8, 0))
        self.acoustid = self._entry(right)
        self._check(right, "Próba: ne írjon a fájlokba", self.dry_run)
        self._check(right, "Meglévő címet és előadót hagyja", self.keep_identity)
        self._check(right, "Borító mentése, ha még nincs", self.embed_cover)
        self._check(right, "Rekordbox XML BPM frissítése", self.write_bpm_to_xml)
        delay_row = tk.Frame(right, bg=PAPER)
        delay_row.pack(fill="x", padx=12, pady=(8, 12))
        tk.Label(delay_row, text="Szünet a fájlok között (mp)", bg=PAPER, fg=MUTED).pack(side="left")
        self.delay = tk.Spinbox(
            delay_row, from_=0, to=10, increment=0.5, width=6, bg=ENTRY, fg=INK, buttonbackground=PAPER, relief="flat"
        )
        self.delay.delete(0, "end")
        self.delay.insert(0, "1.0")
        self.delay.pack(side="right")

        foot = tk.Frame(self, bg=BG)
        foot.pack(fill="both", expand=True, padx=18, pady=(0, 14))
        bar_row = tk.Frame(foot, bg=BG)
        bar_row.pack(fill="x")
        style = ttk.Style(self)
        style.configure(
            "Brass.Horizontal.TProgressbar",
            troughcolor=ENTRY,
            background=BRASS,
            bordercolor=BG,
            lightcolor=BRASS,
            darkcolor=BRASS,
        )
        self.progress = ttk.Progressbar(bar_row, style="Brass.Horizontal.TProgressbar", mode="determinate")
        self.progress.pack(side="left", fill="x", expand=True, padx=(0, 10))
        self.progress_label = tk.Label(bar_row, text="0 / 0", bg=BG, fg=MUTED, width=12, anchor="e")
        self.progress_label.pack(side="right")

        actions = tk.Frame(foot, bg=BG)
        actions.pack(fill="x", pady=(8, 8))
        self.start_btn = self._button(actions, "Indítás", self._start, BRASS)
        self.start_btn.pack(side="left", padx=(0, 8))
        self._button(actions, "Visszavonás", self._undo, PAPER).pack(side="left", padx=(0, 8))
        self._button(actions, "Frissítés", lambda: self._check_update(True), PAPER).pack(side="left", padx=(0, 8))
        self.stop_btn = self._button(actions, "Megállítás", self._stop, CLAY)
        self.stop_btn.pack(side="left")
        self.stop_btn.configure(state="disabled")

        self.log = tk.Text(
            foot,
            height=4,
            bg=ENTRY,
            fg=INK,
            insertbackground=INK,
            relief="flat",
            highlightthickness=0,
            wrap="word",
        )
        self.log.pack(fill="both", expand=True)
        self.log.tag_configure("ok", foreground="#c5dd9a")
        self.log.tag_configure("err", foreground="#e7a090")
        self.log.tag_configure("info", foreground=BRASS)
        self.log.tag_configure("muted", foreground=MUTED)
        self.log.configure(state="disabled")
        self.update_idletasks()
        self._enable_drop()

    def _windows(self) -> bool:
        import sys

        return sys.platform == "win32"

    def _button(self, parent, text, command, color) -> tk.Button:
        return tk.Button(
            parent,
            text=text,
            command=command,
            bg=color,
            fg=BG,
            activebackground=color,
            activeforeground=BG,
            relief="flat",
            padx=12,
            pady=6,
            cursor="hand2",
        )

    def _check(self, parent, text, variable) -> None:
        tk.Checkbutton(
            parent,
            text=text,
            variable=variable,
            bg=PAPER,
            fg=INK,
            selectcolor=ENTRY,
            activebackground=PAPER,
            activeforeground=INK,
            highlightthickness=0,
            anchor="w",
        ).pack(fill="x", padx=10, pady=1)

    def _entry(self, parent, secret: bool = False) -> tk.Entry:
        entry = tk.Entry(
            parent,
            bg=ENTRY,
            fg=INK,
            insertbackground=INK,
            relief="flat",
            show="*" if secret else "",
        )
        entry.pack(fill="x", padx=12, pady=(2, 0), ipady=4)
        return entry

    def _add_folder(self) -> None:
        folder = filedialog.askdirectory(title="Mappa")
        if folder:
            self._add_path(folder)

    def _add_files(self) -> None:
        files = filedialog.askopenfilenames(
            title="Zene vagy Rekordbox XML",
            filetypes=[
                ("Hang és Rekordbox", "*.mp3 *.flac *.m4a *.wav *.aiff *.aif *.ogg *.opus *.xml"),
                ("Rekordbox XML", "*.xml"),
                ("Minden", "*.*"),
            ],
        )
        for file in files:
            self._add_path(file)

    def _enable_drop(self) -> None:
        try:
            from music_id_tagger.dropfiles import hook_dropfiles

            hook_dropfiles(self, self._on_drop)
            hook_dropfiles(self.tree, self._on_drop)
        except Exception:
            return

    def _on_drop(self, paths: list[str]) -> None:
        from music_id_tagger.beatport import parse_beatport_id

        for raw in paths:
            text = raw.decode("utf-8", "replace") if isinstance(raw, bytes) else str(raw)
            text = text.strip().strip('"')
            if not text:
                continue
            ident = parse_beatport_id(text)
            if ident and not Path(text).exists():
                self._store_beatport(ident)
                continue
            self._add_path(text)

    def _assign_beatport(self) -> None:
        from music_id_tagger.beatport import parse_beatport_id

        ident = parse_beatport_id(self.bp_link.get())
        if not ident:
            messagebox.showinfo("Music ID Tagger", "Ez nem Beatport szám-link és nem ID.\nPélda: beatport.com/track/cim/12345678")
            return
        self._store_beatport(ident)
        self.bp_link.delete(0, "end")

    def _store_beatport(self, ident: str) -> None:
        selected = self.tree.selection()
        if not selected:
            messagebox.showinfo("Music ID Tagger", "Előbb jelöld ki a fájlt, amihez ez a Beatport ID tartozik.")
            return
        iid = selected[0]
        path = self.row_paths.get(iid, "")
        if not path:
            return
        self.beatport_links[path] = ident
        self._paint(iid, path, "Vár", f"BP {ident}", "wait")

    def _add_path(self, path: str) -> None:
        if path in self.paths:
            return
        self.paths.append(path)
        name = Path(path).name or path
        iid = self.tree.insert("", "end", values=(name, "Vár", ""), tags=("wait",))
        self.row_paths[iid] = path
        self.rows[path] = iid
        try:
            self.rows[str(Path(path).resolve())] = iid
        except OSError:
            pass
        self.tree.see(iid)

    def _paint(self, iid: str, path: str, state: str, source: str, tag: str) -> None:
        name = Path(path).name or path
        self.tree.item(iid, values=(name, state, source), tags=(tag,))

    def _remove(self) -> None:
        for iid in self.tree.selection():
            path = self.row_paths.pop(iid, "")
            if path:
                self.beatport_links.pop(path, None)
                if path in self.paths:
                    self.paths.remove(path)
            self.rows = {key: value for key, value in self.rows.items() if value != iid}
            self.tree.delete(iid)

    def _load(self) -> None:
        data = load_settings()
        for path in data.get("folders") or []:
            self._add_path(str(path))
        if data.get("beatport_user"):
            self.user.insert(0, str(data["beatport_user"]))
        remembered = load_password(data)
        if remembered:
            self.password.insert(0, remembered)
        if data.get("acoustid_key"):
            self.acoustid.insert(0, str(data["acoustid_key"]))
        if data.get("spotify_client_id"):
            self.spotify_id.insert(0, str(data["spotify_client_id"]))
        remembered_spotify = load_spotify_secret(data)
        if remembered_spotify:
            self.spotify_secret.insert(0, remembered_spotify)
        self.use_shazam.set(bool(data.get("use_shazam", True)))
        self.use_beatport.set(bool(data.get("use_beatport", True)))
        self.use_spotify.set(bool(data.get("use_spotify", True)))
        self.use_open_catalogs.set(bool(data.get("use_open_catalogs", True)))
        self.dry_run.set(bool(data.get("dry_run", True)))
        self.keep_identity.set(bool(data.get("keep_identity", True)))
        self.embed_cover.set(bool(data.get("embed_cover", True)))
        self.write_bpm_to_xml.set(bool(data.get("write_bpm_to_xml", True)))
        if data.get("delay") is not None:
            self.delay.delete(0, "end")
            self.delay.insert(0, str(data["delay"]))

    def _persist(self) -> None:
        try:
            delay = float(str(self.delay.get()).replace(",", "."))
        except ValueError:
            delay = 1.0
        save_settings(
            {
                "folders": self.paths,
                "beatport_user": self.user.get().strip(),
                "beatport_password": self.password.get(),
                "spotify_client_id": self.spotify_id.get().strip(),
                "spotify_client_secret": self.spotify_secret.get(),
                "acoustid_key": self.acoustid.get().strip(),
                "use_shazam": self.use_shazam.get(),
                "use_beatport": self.use_beatport.get(),
                "use_spotify": self.use_spotify.get(),
                "use_open_catalogs": self.use_open_catalogs.get(),
                "dry_run": self.dry_run.get(),
                "keep_identity": self.keep_identity.get(),
                "embed_cover": self.embed_cover.get(),
                "write_bpm_to_xml": self.write_bpm_to_xml.get(),
                "delay": delay,
            }
        )

    def _start(self) -> None:
        if self.worker and self.worker.is_alive():
            return
        if not self.paths:
            messagebox.showinfo("Music ID Tagger", "Előbb adj meg legalább egy mappát vagy fájlt.")
            return
        if not self.use_shazam.get() and not self.use_beatport.get() and not self.use_spotify.get() and not self.use_open_catalogs.get() and not self.acoustid.get().strip():
            messagebox.showinfo("Music ID Tagger", "Kapcsolj be legalább egy forrást: Shazam, Beatport, katalógus, Spotify vagy AcoustID.")
            return
        self._persist()
        try:
            delay = float(str(self.delay.get()).replace(",", "."))
        except ValueError:
            delay = 1.0
        options = Options(
            use_shazam=self.use_shazam.get(),
            use_beatport=self.use_beatport.get(),
            beatport_user=self.user.get().strip(),
            beatport_password=self.password.get(),
            use_spotify=self.use_spotify.get(),
            spotify_client_id=self.spotify_id.get().strip(),
            spotify_client_secret=self.spotify_secret.get(),
            acoustid_key=self.acoustid.get().strip(),
            dry_run=self.dry_run.get(),
            keep_identity=self.keep_identity.get(),
            embed_cover=self.embed_cover.get(),
            delay=delay,
            beatport_by_file=dict(self.beatport_links),
            write_bpm_to_xml=self.write_bpm_to_xml.get(),
            use_open_catalogs=self.use_open_catalogs.get(),
        )
        self.cancel = threading.Event()
        self.urls.clear()
        for iid in self.tree.get_children():
            path = self.row_paths.get(iid, "")
            ident = self.beatport_links.get(path, "")
            self.tree.item(iid, values=(Path(path).name if path else "", "Vár", f"BP {ident}" if ident else ""), tags=("wait",))
        self.start_btn.configure(state="disabled")
        self.stop_btn.configure(state="normal")
        self._write("info", "Indul.")
        self.worker = threading.Thread(target=self._work, args=(options,), daemon=True)
        self.worker.start()

    def _undo(self) -> None:
        from music_id_tagger.undo import list_runs, revert

        runs = list_runs()
        if not runs:
            messagebox.showinfo("Music ID Tagger", "Nincs visszavonható futás.")
            return
        dialog = tk.Toplevel(self)
        dialog.title("Visszavonás")
        dialog.configure(bg=BG)
        dialog.geometry("520x280")
        tk.Label(dialog, text="Melyik futást állítsam vissza?", bg=BG, fg=INK).pack(anchor="w", padx=12, pady=(12, 6))
        box = tk.Listbox(dialog, bg=ENTRY, fg=INK, selectbackground=BRASS, selectforeground=BG, highlightthickness=0)
        box.pack(fill="both", expand=True, padx=12, pady=(0, 8))
        for saved in runs:
            box.insert("end", saved.name)
        box.selection_set(0)

        def go() -> None:
            selected = box.curselection()
            if not selected:
                return
            target = runs[selected[0]]

            def confirm(path) -> bool:
                return messagebox.askyesno(
                    "Visszavonás",
                    f"{path.name} megváltozott a címkézés óta. Visszaállítsam?",
                    parent=dialog,
                )

            revert(target, lambda level, text: self._write(level, text), confirm)
            dialog.destroy()

        self._button(dialog, "Kijelölt visszaállítása", go, BRASS).pack(pady=(0, 12))

    def _work(self, options: Options) -> None:
        stats = run(
            list(self.paths),
            options,
            log=lambda level, text: self.queue.put(("log", level, text)),
            progress=lambda done, total: self.queue.put(("progress", done, total)),
            cancel=self.cancel,
            track=lambda payload: self.queue.put(("track", payload)),
        )
        self.queue.put(("done", stats))

    def _stop(self) -> None:
        self.cancel.set()
        self._write("muted", "Megállítás kérve, a folyamatban lévő fájl még befejeződik.")

    def _drain(self) -> None:
        try:
            while True:
                item = self.queue.get_nowait()
                kind = item[0]
                if kind == "log":
                    self._write(item[1], item[2])
                elif kind == "progress":
                    done, total = item[1], item[2]
                    self.progress["maximum"] = max(total, 1)
                    self.progress["value"] = done
                    self.progress_label.configure(text=f"{done} / {total}")
                elif kind == "track":
                    self._track_row(item[1])
                elif kind == "done":
                    stats = item[1]
                    self.start_btn.configure(state="normal")
                    self.stop_btn.configure(state="disabled")
                    self.spotify_secret.delete(0, "end")
                    if not stats.cancelled:
                        messagebox.showinfo(
                            "Music ID Tagger",
                            f"Siker: {stats.ok}\nNincs találat: {stats.missed}\nHiba: {stats.failed}",
                        )
        except queue.Empty:
            pass
        self.after(120, self._drain)

    def _track_row(self, payload: dict) -> None:
        key = str(payload.get("path") or payload.get("name") or "")
        if not key:
            return
        state = str(payload.get("state") or "wait")
        name = str(payload.get("name") or key)
        detail = str(payload.get("detail") or "")
        link = str(payload.get("label") or "")
        url = str(payload.get("url") or "")
        if not url.startswith("https://"):
            url = ""
            link = ""
        tag = "unsure" if state in {"unsure", "missed"} else "bad" if state == "failed" else state if state in _STATE else "ok"
        label = _STATE.get(state, state)
        source = link
        if not source and detail and state in {"ok", "unsure", "missed", "failed"}:
            source = detail
        iid = self.rows.get(key)
        if not iid or not self.tree.exists(iid):
            for child in self.tree.get_children():
                values = self.tree.item(child, "values")
                if values and values[0] == name:
                    iid = child
                    self.rows[key] = iid
                    break
            else:
                iid = ""
        if iid and self.tree.exists(iid):
            current = self.tree.item(iid, "values")
            if not source and len(current) > 2:
                source = current[2]
            self.tree.item(iid, values=(name, label, source), tags=(tag,))
        else:
            iid = self.tree.insert("", "end", values=(name, label, source), tags=(tag,))
            self.rows[key] = iid
            self.row_paths.setdefault(iid, key)
        self.urls[iid] = url
        self.tree.see(iid)

    def _open_source(self, event) -> None:
        iid = self.tree.identify_row(event.y)
        column = self.tree.identify_column(event.x)
        url = self.urls.get(iid, "")
        if column == "#3" and url.startswith("https://"):
            webbrowser.open(url)

    def _write(self, level: str, text: str) -> None:
        self.log.configure(state="normal")
        self.log.insert("end", text + "\n", level if level in {"ok", "err", "info", "muted"} else "muted")
        self.log.see("end")
        self.log.configure(state="disabled")

    def _check_update(self, manual: bool) -> None:
        if getattr(self, "_updating", False):
            return
        self._updating = True
        threading.Thread(target=self._update_thread, args=(manual,), daemon=True).start()

    def _update_thread(self, manual: bool) -> None:
        from music_id_tagger.updatecheck import check_update

        try:
            info = check_update(__version__)
        except Exception:
            info = None

        def finish() -> None:
            self._updating = False
            if not info:
                if manual:
                    messagebox.showinfo("Music ID Tagger", "Nincs újabb verzió, vagy a frissítés most nem elérhető.")
                return
            if not messagebox.askyesno(
                "Music ID Tagger",
                f"Van újabb verzió ({info['version']}). Letöltsem és elindítsam a telepítőt?",
            ):
                return
            self._write("info", f"Frissítés letöltése: {info['version']}")
            threading.Thread(target=self._download_update, args=(info,), daemon=True).start()

        self.after(0, finish)

    def _download_update(self, info: dict) -> None:
        import tempfile

        from music_id_tagger.updatecheck import download, launch_installer

        dest = Path(tempfile.gettempdir()) / "MusicIDTagger-Setup.exe"
        try:
            download(info["url"], dest)
        except Exception as exc:
            message = str(exc)
            self.after(0, lambda message=message: messagebox.showerror("Music ID Tagger", f"A frissítést nem tudtam letölteni: {message}"))
            return

        def install() -> None:
            self._write("ok", "A telepítő indul. A program bezárul.")
            launch_installer(dest)
            self._persist()
            self.destroy()

        self.after(0, install)

    def _close(self) -> None:
        self._persist()
        self.cancel.set()
        self.destroy()


def run_gui() -> None:
    import sys

    if sys.platform == "win32":
        try:
            import ctypes

            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            try:
                import ctypes

                ctypes.windll.user32.SetProcessDPIAware()
            except Exception:
                pass
    app = App()
    app.mainloop()
