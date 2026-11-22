from __future__ import annotations

import queue
import threading
import tkinter as tk
import webbrowser
from pathlib import Path
from tkinter import filedialog, font as tkfont, messagebox, ttk

from music_id_tagger.config import load_password, load_settings, save_settings
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
    "wait": "Várakozik",
    "run": "Keres…",
    "ok": "Kész",
    "unsure": "! Bizonytalan",
    "missed": "! Nincs találat",
    "failed": "Hiba",
}


class App(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Music ID Tagger")
        self.geometry("980x780")
        self.minsize(860, 680)
        self.configure(bg=BG)
        self.queue: queue.Queue = queue.Queue()
        self.cancel = threading.Event()
        self.worker: threading.Thread | None = None
        self.paths: list[str] = []
        self.beatport_links: dict[str, str] = {}
        self.rows: dict[str, str] = {}
        self.urls: dict[str, str] = {}
        self._fonts: list[tkfont.Font] = []
        self._build()
        self._load()
        self.after(120, self._drain)
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
            text="Húzd ide a mappát, a zenét vagy a Rekordbox XML-t.",
            bg=PAPER,
            fg=MUTED,
        ).pack(anchor="w", padx=12, pady=(0, 6))
        self.listbox = tk.Listbox(
            left,
            bg=ENTRY,
            fg=INK,
            selectbackground=BRASS,
            selectforeground=BG,
            highlightthickness=0,
            relief="flat",
            activestyle="none",
        )
        self.listbox.pack(fill="both", expand=True, padx=12, pady=(0, 8))
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
        self.dry_run = tk.BooleanVar(value=True)
        self.keep_identity = tk.BooleanVar(value=True)
        self.embed_cover = tk.BooleanVar(value=True)
        self._check(right, "Shazam hangminta", self.use_shazam)
        self._check(right, "Beatport (BPM, hangnem, stílus)", self.use_beatport)
        tk.Label(right, text="Beatport felhasználó", bg=PAPER, fg=MUTED).pack(anchor="w", padx=12, pady=(8, 0))
        self.user = self._entry(right)
        tk.Label(right, text="Jelszó  ·  erre a gépre emlékezik", bg=PAPER, fg=MUTED).pack(anchor="w", padx=12, pady=(8, 0))
        self.password = self._entry(right, secret=True)
        self._check(right, "Spotify (album, év, ISRC)", self.use_spotify)
        tk.Label(right, text="Spotify Client ID", bg=PAPER, fg=MUTED).pack(anchor="w", padx=12, pady=(8, 0))
        self.spotify_id = self._entry(right)
        tk.Label(right, text="Spotify Client Secret  ·  nem mentjük el", bg=PAPER, fg=MUTED).pack(
            anchor="w", padx=12, pady=(8, 0)
        )
        self.spotify_secret = self._entry(right, secret=True)
        tk.Label(right, text="AcoustID kulcs  ·  nem kötelező", bg=PAPER, fg=MUTED).pack(anchor="w", padx=12, pady=(8, 0))
        self.acoustid = self._entry(right)
        self._check(right, "Próba: ne írjon a fájlokba", self.dry_run)
        self._check(right, "Meglévő címet és előadót hagyja", self.keep_identity)
        self._check(right, "Borító mentése, ha még nincs", self.embed_cover)
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
        style.theme_use("clam")
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
        self.stop_btn = self._button(actions, "Megállítás", self._stop, CLAY)
        self.stop_btn.pack(side="left")
        self.stop_btn.configure(state="disabled")

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
        list_wrap = tk.Frame(foot, bg=BG)
        list_wrap.pack(fill="both", expand=True, pady=(0, 8))
        self.tree = ttk.Treeview(
            list_wrap,
            columns=("file", "state", "found", "source"),
            show="headings",
            style="Tracks.Treeview",
            height=8,
        )
        self.tree.heading("file", text="Fájl")
        self.tree.heading("state", text="Állapot")
        self.tree.heading("found", text="Találat")
        self.tree.heading("source", text="Forrás")
        self.tree.column("file", width=260, stretch=True)
        self.tree.column("state", width=140, stretch=False, anchor="w")
        self.tree.column("found", width=280, stretch=True)
        self.tree.column("source", width=110, stretch=False, anchor="w")
        self.tree.tag_configure("ok", foreground=INK)
        self.tree.tag_configure("run", foreground=BRASS)
        self.tree.tag_configure("wait", foreground=MUTED)
        self.tree.tag_configure("unsure", foreground=WARN)
        self.tree.tag_configure("missed", foreground=WARN)
        self.tree.tag_configure("bad", foreground=CLAY)
        self.tree.tag_configure("link", foreground=LINK)
        scroll = ttk.Scrollbar(list_wrap, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        self.tree.bind("<ButtonRelease-1>", self._open_source)

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
            hook_dropfiles(self.listbox, self._on_drop)
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
        selected = self.listbox.curselection()
        if not selected:
            messagebox.showinfo("Music ID Tagger", "Előbb jelöld ki a fájlt, amihez ez a Beatport ID tartozik.")
            return
        index = selected[0]
        path = self.paths[index]
        self.beatport_links[path] = ident
        self._show_path(index)

    def _add_path(self, path: str) -> None:
        if path not in self.paths:
            self.paths.append(path)
            self.listbox.insert("end", path)

    def _show_path(self, index: int) -> None:
        path = self.paths[index]
        ident = self.beatport_links.get(path, "")
        label = f"{path}    BP {ident}" if ident else path
        self.listbox.delete(index)
        self.listbox.insert(index, label)
        self.listbox.selection_set(index)

    def _remove(self) -> None:
        selected = list(self.listbox.curselection())
        for index in reversed(selected):
            self.beatport_links.pop(self.paths[index], None)
            self.listbox.delete(index)
            del self.paths[index]

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
        self.use_shazam.set(bool(data.get("use_shazam", True)))
        self.use_beatport.set(bool(data.get("use_beatport", True)))
        self.use_spotify.set(bool(data.get("use_spotify", True)))
        self.dry_run.set(bool(data.get("dry_run", True)))
        self.keep_identity.set(bool(data.get("keep_identity", True)))
        self.embed_cover.set(bool(data.get("embed_cover", True)))
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
                "acoustid_key": self.acoustid.get().strip(),
                "use_shazam": self.use_shazam.get(),
                "use_beatport": self.use_beatport.get(),
                "use_spotify": self.use_spotify.get(),
                "dry_run": self.dry_run.get(),
                "keep_identity": self.keep_identity.get(),
                "embed_cover": self.embed_cover.get(),
                "delay": delay,
            }
        )

    def _start(self) -> None:
        if self.worker and self.worker.is_alive():
            return
        if not self.paths:
            messagebox.showinfo("Music ID Tagger", "Előbb adj meg legalább egy mappát vagy fájlt.")
            return
        if not self.use_shazam.get() and not self.use_beatport.get() and not self.use_spotify.get() and not self.acoustid.get().strip():
            messagebox.showinfo("Music ID Tagger", "Kapcsolj be legalább egy forrást: Shazam, Beatport, Spotify vagy AcoustID.")
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
        )
        self.cancel = threading.Event()
        self.rows.clear()
        self.urls.clear()
        self.tree.delete(*self.tree.get_children())
        self.start_btn.configure(state="disabled")
        self.stop_btn.configure(state="normal")
        self._write("info", "Indul.")
        self.worker = threading.Thread(target=self._work, args=(options,), daemon=True)
        self.worker.start()

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
        values = (name, _STATE.get(state, state), detail, link)
        iid = self.rows.get(key)
        if iid and self.tree.exists(iid):
            self.tree.item(iid, values=values, tags=(tag,))
        else:
            iid = self.tree.insert("", "end", values=values, tags=(tag,))
            self.rows[key] = iid
        self.urls[iid] = url
        self.tree.see(iid)

    def _open_source(self, event) -> None:
        iid = self.tree.identify_row(event.y)
        column = self.tree.identify_column(event.x)
        url = self.urls.get(iid, "")
        if column == "#4" and url.startswith("https://"):
            webbrowser.open(url)

    def _write(self, level: str, text: str) -> None:
        self.log.configure(state="normal")
        self.log.insert("end", text + "\n", level if level in {"ok", "err", "info", "muted"} else "muted")
        self.log.see("end")
        self.log.configure(state="disabled")

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
