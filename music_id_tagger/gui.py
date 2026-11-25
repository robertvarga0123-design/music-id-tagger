from __future__ import annotations

import queue
import threading
import time
import tkinter as tk
import webbrowser
from pathlib import Path
from tkinter import filedialog, font as tkfont, messagebox, ttk

from music_id_tagger import __version__
from music_id_tagger.config import load_gemini_key, load_grok_key, load_password, load_settings, load_spotify_secret, save_settings
from music_id_tagger.engine import Options, run
from music_id_tagger.pending import (
    FIELDS,
    LogBook,
    Pending,
    eta_text,
    field_enabled,
    filter_pending,
    parse_genre_map,
    preview_changes,
    select_for_apply,
    summary_line,
)

BG = "#10110f"
PAPER = "#1c1d18"
INK = "#f3f0e7"
MUTED = "#a39e90"
BRASS = "#e0a84a"
CLAY = "#d4654a"
ENTRY = "#26271f"
LINE = "#3a3b32"
WARN = "#f2c14e"
OK = "#c5dd9a"

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
    "ai": "AI…",
    "write": "Írás…",
    "ok": "Kész",
    "unsure": "Bizonytalan",
    "missed": "Nincs találat",
    "rejected": "AI nem",
    "failed": "Hiba",
    "skipped": "Kihagyva",
    "applied": "Beírva",
}

_FIELDS = (
    ("identity", "Cím és előadó"),
    ("bpm", "BPM"),
    ("key", "Hangnem"),
    ("genre", "Műfaj"),
    ("label", "Kiadó"),
    ("isrc", "ISRC"),
    ("cover", "Borító"),
    ("year", "Év"),
    ("album", "Album"),
)

_FILTERS = (
    ("Mind", "all"),
    ("Bizonytalan", "unsure"),
    ("Nincs találat", "missed"),
    ("Hiba", "failed"),
    ("Változás van", "changed"),
)

_KEYS = (
    ("Camelot (8A)", "camelot"),
    ("Open Key (1m)", "open"),
    ("Hagyományos (Am)", "traditional"),
)


class App(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title(f"Music ID Tagger {__version__}")
        self.geometry("1100x820")
        self.minsize(920, 680)
        self.configure(bg=BG)
        self.queue: queue.Queue = queue.Queue()
        self.cancel = threading.Event()
        self.worker: threading.Thread | None = None
        self.paths: list[str] = []
        self.beatport_links: dict[str, str] = {}
        self.rows: dict[str, str] = {}
        self.row_paths: dict[str, str] = {}
        self.pending: list[Pending] = []
        self.result_rows: dict[str, str] = {}
        self.xmls: list[str] = []
        self.book = LogBook()
        self._fonts: list[tkfont.Font] = []
        self._cover_image = None
        self._started = 0.0
        self._updating = False
        self._build()
        self._load()
        self.after(120, self._drain)
        self.after(1500, lambda: self._check_update(False))
        self.protocol("WM_DELETE_WINDOW", self._close)
        self.bind("<Return>", self._on_enter)
        self.bind("<Delete>", self._on_delete)
        self.bind("<Control-f>", self._on_find)

    def _face(self, size: int, bold: bool = False) -> tkfont.Font:
        family = "Segoe UI" if self._windows() else "DejaVu Sans"
        item = tkfont.Font(family=family, size=max(size, 10), weight="bold" if bold else "normal")
        self._fonts.append(item)
        return item

    def _windows(self) -> bool:
        import sys

        return sys.platform == "win32"

    def _build(self) -> None:
        self.option_add("*Font", str(self._face(10)))
        head = tk.Frame(self, bg=BG)
        head.pack(fill="x", padx=16, pady=(12, 4))
        tk.Label(head, text="Music ID Tagger", bg=BG, fg=BRASS, font=self._face(18, True)).pack(side="left")
        tk.Label(head, text="Keresés, átnézés, aztán alkalmazás. Előbb semmi nem íródik.", bg=BG, fg=MUTED).pack(
            side="left", padx=(12, 0)
        )

        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure("TNotebook", background=BG, borderwidth=0)
        style.configure("TNotebook.Tab", background=PAPER, foreground=INK, padding=(14, 6), font=str(self._face(10, True)))
        style.map("TNotebook.Tab", background=[("selected", ENTRY)], foreground=[("selected", BRASS)])
        style.configure("Tracks.Treeview", background=ENTRY, fieldbackground=ENTRY, foreground=INK, borderwidth=0, rowheight=26, font=str(self._face(10)))
        style.configure("Tracks.Treeview.Heading", background=PAPER, foreground=MUTED, relief="flat", font=str(self._face(10, True)))
        style.map("Tracks.Treeview", background=[("selected", "#3a3424")], foreground=[("selected", INK)])
        style.configure("Brass.Horizontal.TProgressbar", troughcolor=ENTRY, background=BRASS, bordercolor=BG, lightcolor=BRASS, darkcolor=BRASS)

        self.book_tabs = ttk.Notebook(self)
        self.book_tabs.pack(fill="both", expand=True, padx=16, pady=8)
        self._build_library()
        self._build_results()
        self._build_settings()
        self._build_log()
        self._build_status()
        self.update_idletasks()
        self._enable_drop()
        self._refresh_empty()

    def _build_library(self) -> None:
        tab = tk.Frame(self.book_tabs, bg=PAPER)
        self.book_tabs.add(tab, text="Könyvtár")
        tk.Label(tab, text="Mappák, fájlok, Rekordbox XML", bg=PAPER, fg=INK, font=self._face(12, True)).pack(anchor="w", padx=12, pady=(12, 4))
        self.empty = tk.Label(
            tab,
            text="Húzd ide a mappát, a zenét vagy a Rekordbox XML-t.",
            bg=PAPER,
            fg=BRASS,
            font=self._face(14, True),
        )
        wrap = tk.Frame(tab, bg=PAPER)
        wrap.pack(fill="both", expand=True, padx=12, pady=8)
        self.tree = ttk.Treeview(wrap, columns=("file", "state"), show="headings", style="Tracks.Treeview")
        self.tree.heading("file", text="Fájl")
        self.tree.heading("state", text="Hol tart")
        self.tree.column("file", width=520, stretch=True)
        self.tree.column("state", width=180, stretch=False)
        for name, color in (("wait", MUTED), ("run", BRASS), ("ok", OK), ("unsure", WARN), ("missed", WARN), ("bad", CLAY)):
            self.tree.tag_configure(name, foreground=color)
        scroll = ttk.Scrollbar(wrap, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        buttons = tk.Frame(tab, bg=PAPER)
        buttons.pack(fill="x", padx=12, pady=(0, 8))
        self._button(buttons, "Mappa", self._add_folder, BRASS).pack(side="left", padx=(0, 6))
        self._button(buttons, "Fájlok", self._add_files, BRASS).pack(side="left", padx=(0, 6))
        self._button(buttons, "Kijelölt törlése", self._remove, CLAY).pack(side="left")
        modes = tk.Frame(tab, bg=PAPER)
        modes.pack(fill="x", padx=12, pady=(0, 12))
        self.rescan = tk.BooleanVar(value=False)
        self.fill_missing = tk.BooleanVar(value=False)
        self.tag_first = tk.BooleanVar(value=False)
        self._check(modes, "Újrakeresés (cache mellőzése)", self.rescan)
        self._check(modes, "Csak a hiányzó mezőket töltse ki", self.fill_missing)
        self._check(modes, "Taggel először: Beatport, Shazam csak ha kell", self.tag_first)

    def _build_results(self) -> None:
        tab = tk.Frame(self.book_tabs, bg=PAPER)
        self.book_tabs.add(tab, text="Eredmények")
        tab.columnconfigure(0, weight=3)
        tab.columnconfigure(1, weight=2)
        tab.rowconfigure(1, weight=1)
        bar = tk.Frame(tab, bg=PAPER)
        bar.grid(row=0, column=0, columnspan=2, sticky="ew", padx=12, pady=(10, 4))
        tk.Label(bar, text="Szűrő", bg=PAPER, fg=MUTED).pack(side="left")
        self.filter_box = ttk.Combobox(bar, values=[label for label, _key in _FILTERS], state="readonly", width=18)
        self.filter_box.set("Mind")
        self.filter_box.pack(side="left", padx=(6, 0))
        self.filter_box.bind("<<ComboboxSelected>>", lambda _e: self._fill_results())
        left = tk.Frame(tab, bg=PAPER)
        left.grid(row=1, column=0, sticky="nsew", padx=(12, 6), pady=6)
        self.results = ttk.Treeview(
            left,
            columns=("state", "file", "change", "source", "confidence"),
            show="headings",
            style="Tracks.Treeview",
        )
        for key, title, width in (
            ("state", "Állapot", 120),
            ("file", "Fájl", 180),
            ("change", "Régi → új", 260),
            ("source", "Forrás", 110),
            ("confidence", "Megbízhatóság", 110),
        ):
            self.results.heading(key, text=title)
            self.results.column(key, width=width, stretch=key == "change")
        for name, color in (("ok", OK), ("unsure", WARN), ("missed", WARN), ("failed", CLAY), ("applied", BRASS)):
            self.results.tag_configure(name, foreground=color)
        result_scroll = ttk.Scrollbar(left, orient="vertical", command=self.results.yview)
        self.results.configure(yscrollcommand=result_scroll.set)
        self.results.pack(side="left", fill="both", expand=True)
        result_scroll.pack(side="right", fill="y")
        self.results.bind("<<TreeviewSelect>>", lambda _e: self._show_detail())
        self.results.bind("<Double-1>", self._on_result_double)
        self.detail = tk.Frame(tab, bg=ENTRY)
        self.detail.grid(row=1, column=1, sticky="nsew", padx=(6, 12), pady=6)
        actions = tk.Frame(tab, bg=PAPER)
        actions.grid(row=2, column=0, columnspan=2, sticky="ew", padx=12, pady=(0, 10))
        self._button(actions, "Kijelöltek alkalmazása", lambda: self._apply("selected"), BRASS).pack(side="left", padx=(0, 6))
        self._button(actions, "Összes biztos alkalmazása", lambda: self._apply("sure"), BRASS).pack(side="left", padx=(0, 6))
        self._button(actions, "Visszavonás", self._undo, PAPER).pack(side="left", padx=(0, 6))
        self._button(actions, "CSV", self._export_csv, PAPER).pack(side="left", padx=(0, 6))
        self._button(actions, "Duplikátumok", self._duplicates, PAPER).pack(side="left")
        self._show_detail()

    def _build_settings(self) -> None:
        tab = tk.Frame(self.book_tabs, bg=PAPER)
        self.book_tabs.add(tab, text="Beállítások")
        canvas = tk.Canvas(tab, bg=PAPER, highlightthickness=0, borderwidth=0)
        scroll = ttk.Scrollbar(tab, orient="vertical", command=canvas.yview)
        inner = tk.Frame(canvas, bg=PAPER)
        window = canvas.create_window((0, 0), window=inner, anchor="nw")
        inner.bind("<Configure>", lambda _e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda event: canvas.itemconfigure(window, width=event.width))
        canvas.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        canvas.configure(yscrollcommand=scroll.set)

        self.use_shazam = tk.BooleanVar(value=True)
        self.use_beatport = tk.BooleanVar(value=True)
        self.use_spotify = tk.BooleanVar(value=True)
        self.use_deezer = tk.BooleanVar(value=True)
        self.use_apple = tk.BooleanVar(value=True)
        self.use_musicbrainz = tk.BooleanVar(value=True)
        self.use_discogs = tk.BooleanVar(value=True)
        self.use_websearch = tk.BooleanVar(value=False)
        self.forget_secrets = tk.BooleanVar(value=False)
        self.keep_identity = tk.BooleanVar(value=True)
        self.embed_cover = tk.BooleanVar(value=True)
        self.write_bpm_to_xml = tk.BooleanVar(value=True)
        tk.Label(inner, text="Szolgáltatók", bg=PAPER, fg=INK, font=self._face(12, True)).pack(anchor="w", padx=12, pady=(12, 4))
        self._check(inner, "Shazam hangminta. Hangminta megy ki, útvonal nem.", self.use_shazam)
        self._check(inner, "Beatport. Belépés után előadó, cím vagy ID.", self.use_beatport)
        tk.Label(inner, text="Beatport felhasználó", bg=PAPER, fg=MUTED).pack(anchor="w", padx=12, pady=(6, 0))
        self.user = self._entry(inner)
        tk.Label(inner, text="Jelszó  ·  erre a gépre emlékezik", bg=PAPER, fg=MUTED).pack(anchor="w", padx=12, pady=(6, 0))
        self.password = self._entry(inner, secret=True)
        self._check(inner, "Spotify (album, év, ISRC). Kulcs kell, jelszó nem.", self.use_spotify)
        tk.Label(inner, text="Spotify Client ID", bg=PAPER, fg=MUTED).pack(anchor="w", padx=12)
        self.spotify_id = self._entry(inner)
        tk.Label(inner, text="Spotify Client Secret", bg=PAPER, fg=MUTED).pack(anchor="w", padx=12, pady=(6, 0))
        self.spotify_secret = self._entry(inner, secret=True)
        self._check(inner, "Deezer", self.use_deezer)
        self._check(inner, "Apple", self.use_apple)
        self._check(inner, "MusicBrainz", self.use_musicbrainz)
        self._check(inner, "Discogs", self.use_discogs)
        self._check(inner, "Webes keresés. A számcímek a Bingnek kerülnek.", self.use_websearch)
        tk.Label(inner, text="AcoustID kulcs  ·  nem kötelező", bg=PAPER, fg=MUTED).pack(anchor="w", padx=12, pady=(6, 0))
        self.acoustid = self._entry(inner)
        tk.Label(inner, text="Grok kulcs  ·  erre a gépre emlékezik", bg=PAPER, fg=MUTED).pack(anchor="w", padx=12, pady=(6, 0))
        self.grok_key = self._entry(inner, secret=True)
        tk.Label(inner, text="Gemini kulcs  ·  erre a gépre emlékezik", bg=PAPER, fg=MUTED).pack(anchor="w", padx=12, pady=(6, 0))
        self.gemini_key = self._entry(inner, secret=True)
        self._check(inner, "Ne jegyezze meg a jelszavakat", self.forget_secrets)
        tk.Label(inner, text="Írandó mezők", bg=PAPER, fg=INK, font=self._face(12, True)).pack(anchor="w", padx=12, pady=(12, 4))
        self.field_vars = {}
        for name, label in _FIELDS:
            var = tk.BooleanVar(value=True)
            self.field_vars[name] = var
            self._check(inner, label, var)
        self._check(inner, "Meglévő címet és előadót hagyja", self.keep_identity)
        self._check(inner, "Borító mentése, ha még nincs", self.embed_cover)
        self._check(inner, "Rekordbox XML BPM frissítése", self.write_bpm_to_xml)
        tk.Label(inner, text="Hangnem formátuma", bg=PAPER, fg=MUTED).pack(anchor="w", padx=12, pady=(8, 0))
        self.key_box = ttk.Combobox(inner, values=[label for label, _style in _KEYS], state="readonly")
        self.key_box.set(_KEYS[0][0])
        self.key_box.pack(anchor="w", padx=12, pady=(2, 0))
        tk.Label(inner, text="Fájlnév sablon, üresen kikapcsolva", bg=PAPER, fg=MUTED).pack(anchor="w", padx=12, pady=(8, 0))
        self.rename_box = self._entry(inner)
        tk.Label(inner, text="Példa: {artist} - {title} ({key} {bpm})", bg=PAPER, fg=MUTED).pack(anchor="w", padx=12)
        delay_row = tk.Frame(inner, bg=PAPER)
        delay_row.pack(fill="x", padx=12, pady=(8, 4))
        tk.Label(delay_row, text="Szünet a fájlok között (mp)", bg=PAPER, fg=MUTED).pack(side="left")
        self.delay = tk.Spinbox(delay_row, from_=0, to=10, increment=0.5, width=6, bg=ENTRY, fg=INK, buttonbackground=PAPER, relief="flat")
        self.delay.delete(0, "end")
        self.delay.insert(0, "1.0")
        self.delay.pack(side="right")
        tk.Label(inner, text="Műfaj-leképezés", bg=PAPER, fg=INK, font=self._face(12, True)).pack(anchor="w", padx=12, pady=(12, 4))
        tk.Label(inner, text="Beatport címke → saját címke. Csak íráskor cserél.", bg=PAPER, fg=MUTED).pack(anchor="w", padx=12)
        self.genre_tree = ttk.Treeview(inner, columns=("src", "dst"), show="headings", height=5, style="Tracks.Treeview")
        self.genre_tree.heading("src", text="Beatport")
        self.genre_tree.heading("dst", text="Saját")
        self.genre_tree.column("src", width=280)
        self.genre_tree.column("dst", width=180)
        self.genre_tree.pack(fill="x", padx=12, pady=(4, 4))
        genre_row = tk.Frame(inner, bg=PAPER)
        genre_row.pack(fill="x", padx=12, pady=(0, 8))
        self.genre_from = tk.Entry(genre_row, bg=ENTRY, fg=INK, insertbackground=INK, relief="flat")
        self.genre_to = tk.Entry(genre_row, bg=ENTRY, fg=INK, insertbackground=INK, relief="flat")
        self.genre_from.pack(side="left", fill="x", expand=True, ipady=3, padx=(0, 4))
        self.genre_to.pack(side="left", fill="x", expand=True, ipady=3, padx=(0, 4))
        self._button(genre_row, "Hozzáad", self._add_genre, BRASS).pack(side="left", padx=(0, 4))
        self._button(genre_row, "Töröl", self._delete_genre, CLAY).pack(side="left")
        tools = tk.Frame(inner, bg=PAPER)
        tools.pack(fill="x", padx=12, pady=(4, 16))
        self._button(tools, "Cache törlése", self._clear_cache, PAPER).pack(side="left", padx=(0, 6))
        self._button(tools, "Frissítés", lambda: self._check_update(True), PAPER).pack(side="left")

    def _build_log(self) -> None:
        tab = tk.Frame(self.book_tabs, bg=PAPER)
        self.book_tabs.add(tab, text="Napló")
        bar = tk.Frame(tab, bg=PAPER)
        bar.pack(fill="x", padx=12, pady=(10, 4))
        tk.Label(bar, text="Szint", bg=PAPER, fg=MUTED).pack(side="left")
        self.log_level = ttk.Combobox(bar, values=["Mind", "Info", "Hiba"], state="readonly", width=12)
        self.log_level.set("Mind")
        self.log_level.pack(side="left", padx=(6, 8))
        self.log_level.bind("<<ComboboxSelected>>", lambda _e: self._repaint_log())
        self._button(bar, "Másolás", self._copy_log, PAPER).pack(side="left", padx=(0, 6))
        self._button(bar, "Mentés fájlba", self._save_log, PAPER).pack(side="left")
        self.log = tk.Text(tab, bg=ENTRY, fg=INK, insertbackground=INK, relief="flat", wrap="word", font=str(self._face(10)))
        self.log.pack(fill="both", expand=True, padx=12, pady=(0, 12))
        self.log.tag_configure("ok", foreground=OK)
        self.log.tag_configure("err", foreground="#e7a090")
        self.log.tag_configure("info", foreground=BRASS)
        self.log.tag_configure("muted", foreground=MUTED)
        self.log.configure(state="disabled")

    def _build_status(self) -> None:
        foot = tk.Frame(self, bg=BG)
        foot.pack(fill="x", padx=16, pady=(0, 12))
        actions = tk.Frame(foot, bg=BG)
        actions.pack(fill="x", pady=(0, 6))
        self.start_btn = self._button(actions, "Keresés", self._start, BRASS)
        self.start_btn.pack(side="left", padx=(0, 8))
        self.stop_btn = self._button(actions, "Megállítás", self._stop, CLAY)
        self.stop_btn.pack(side="left")
        self.stop_btn.configure(state="disabled")
        self.providers = tk.Label(actions, text="", bg=BG, fg=MUTED)
        self.providers.pack(side="right")
        row = tk.Frame(foot, bg=BG)
        row.pack(fill="x")
        self.progress = ttk.Progressbar(row, style="Brass.Horizontal.TProgressbar", mode="determinate")
        self.progress.pack(side="left", fill="x", expand=True, padx=(0, 8))
        self.progress_label = tk.Label(row, text="0 fájl", bg=BG, fg=INK, width=18, anchor="e")
        self.progress_label.pack(side="right")
        self.eta_label = tk.Label(row, text="", bg=BG, fg=MUTED, width=14, anchor="e")
        self.eta_label.pack(side="right")

    def _button(self, parent, text, command, color) -> tk.Button:
        fg = BG if color != PAPER else INK
        return tk.Button(
            parent,
            text=text,
            command=command,
            bg=color,
            fg=fg,
            activebackground=color,
            activeforeground=fg,
            relief="flat",
            padx=12,
            pady=6,
            cursor="hand2",
            font=self._face(10, True),
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
            font=self._face(10),
        ).pack(fill="x", padx=10, pady=1)

    def _entry(self, parent, secret: bool = False) -> tk.Entry:
        entry = tk.Entry(parent, bg=ENTRY, fg=INK, insertbackground=INK, relief="flat", show="*" if secret else "", font=self._face(10))
        entry.pack(fill="x", padx=12, pady=(2, 0), ipady=4)
        return entry

    def _typing(self) -> bool:
        widget = self.focus_get()
        return isinstance(widget, (tk.Entry, tk.Text, tk.Spinbox, ttk.Combobox))

    def _on_enter(self, _event=None):
        if self._typing():
            return
        self._apply("selected")
        return "break"

    def _on_delete(self, _event=None):
        if self._typing():
            return
        current = self.book_tabs.index(self.book_tabs.select()) if self.book_tabs.select() else 0
        if current == 1:
            self._drop_result_rows()
        else:
            self._remove()
        return "break"

    def _on_find(self, _event=None):
        self.book_tabs.select(1)
        self.filter_box.focus_set()
        return "break"

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
            hook_dropfiles(self.empty, self._on_drop)
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
        self.tree.item(iid, values=(Path(path).name, f"BP {ident}"), tags=("wait",))

    def _add_path(self, path: str) -> None:
        if path in self.paths:
            return
        self.paths.append(path)
        name = Path(path).name or path
        iid = self.tree.insert("", "end", values=(name, "Vár"), tags=("wait",))
        self.row_paths[iid] = path
        self.rows[path] = iid
        try:
            self.rows[str(Path(path).resolve())] = iid
        except OSError:
            pass
        self.tree.see(iid)
        self._refresh_empty()
        self._paint_providers()

    def _refresh_empty(self) -> None:
        if self.paths:
            self.empty.place_forget()
        else:
            self.empty.place(relx=0.5, rely=0.45, anchor="center")

    def _remove(self) -> None:
        for iid in self.tree.selection():
            path = self.row_paths.pop(iid, "")
            if path:
                self.beatport_links.pop(path, None)
                if path in self.paths:
                    self.paths.remove(path)
            self.rows = {key: value for key, value in self.rows.items() if value != iid}
            self.tree.delete(iid)
        self._refresh_empty()

    def _drop_result_rows(self) -> None:
        selected = set(self.results.selection())
        paths = {self.result_rows[iid] for iid in selected if iid in self.result_rows}
        if not paths:
            return
        self.pending = [item for item in self.pending if item.path not in paths]
        self._fill_results()

    def _enabled_map(self) -> dict:
        return {name: bool(var.get()) for name, var in self.field_vars.items()}

    def _key_style(self) -> str:
        label = self.key_box.get()
        for text, style in _KEYS:
            if text == label:
                return style
        return "camelot"

    def _genre_map(self) -> dict:
        found = {}
        for iid in self.genre_tree.get_children():
            values = self.genre_tree.item(iid, "values")
            if len(values) >= 2 and values[0] and values[1]:
                found[str(values[0])] = str(values[1])
        return found

    def _add_genre(self) -> None:
        left = self.genre_from.get().strip()
        right = self.genre_to.get().strip()
        if not left or not right:
            return
        self.genre_tree.insert("", "end", values=(left, right))
        self.genre_from.delete(0, "end")
        self.genre_to.delete(0, "end")

    def _delete_genre(self) -> None:
        for iid in self.genre_tree.selection():
            self.genre_tree.delete(iid)

    def _clear_cache(self) -> None:
        from music_id_tagger.cache import clear

        clear()
        self._write("info", "A cache törölve. A következő keresés újra hálózatot kérdez.")

    def _delay_value(self) -> float:
        try:
            return float(str(self.delay.get()).replace(",", "."))
        except ValueError:
            return 1.0

    def _options(self) -> Options:
        return Options(
            use_shazam=self.use_shazam.get(),
            use_beatport=self.use_beatport.get(),
            beatport_user=self.user.get().strip(),
            beatport_password=self.password.get(),
            use_spotify=self.use_spotify.get(),
            spotify_client_id=self.spotify_id.get().strip(),
            spotify_client_secret=self.spotify_secret.get(),
            acoustid_key=self.acoustid.get().strip(),
            grok_key=self.grok_key.get().strip(),
            gemini_key=self.gemini_key.get().strip(),
            dry_run=True,
            defer_write=True,
            keep_identity=self.keep_identity.get(),
            embed_cover=self.embed_cover.get(),
            delay=self._delay_value(),
            beatport_by_file=dict(self.beatport_links),
            write_bpm_to_xml=self.write_bpm_to_xml.get(),
            use_open_catalogs=True,
            use_deezer=self.use_deezer.get(),
            use_apple=self.use_apple.get(),
            use_musicbrainz=self.use_musicbrainz.get(),
            use_discogs=self.use_discogs.get(),
            use_websearch=self.use_websearch.get(),
            rescan=self.rescan.get(),
            fill_missing_only=self.fill_missing.get(),
            tag_first=self.tag_first.get(),
            key_format=self._key_style(),
            rename_template=self.rename_box.get().strip(),
            enabled_fields=self._enabled_map(),
            genre_map=self._genre_map(),
        )

    def _load(self) -> None:
        data = load_settings()
        for path in data.get("folders") or []:
            self._add_path(str(path))
        if data.get("beatport_user"):
            self.user.insert(0, str(data["beatport_user"]))
        if data.get("acoustid_key"):
            self.acoustid.insert(0, str(data["acoustid_key"]))
        if data.get("spotify_client_id"):
            self.spotify_id.insert(0, str(data["spotify_client_id"]))
        if data.get("remember_secrets", True):
            for value, widget in (
                (load_password(data), self.password),
                (load_spotify_secret(data), self.spotify_secret),
                (load_grok_key(data), self.grok_key),
                (load_gemini_key(data), self.gemini_key),
            ):
                if value:
                    widget.insert(0, value)
        catalogs = bool(data.get("use_open_catalogs", True))
        self.use_shazam.set(bool(data.get("use_shazam", True)))
        self.use_beatport.set(bool(data.get("use_beatport", True)))
        self.use_spotify.set(bool(data.get("use_spotify", True)))
        self.use_deezer.set(bool(data.get("use_deezer", catalogs)))
        self.use_apple.set(bool(data.get("use_apple", catalogs)))
        self.use_musicbrainz.set(bool(data.get("use_musicbrainz", catalogs)))
        self.use_discogs.set(bool(data.get("use_discogs", catalogs)))
        self.use_websearch.set(bool(data.get("use_websearch", False)))
        self.forget_secrets.set(not bool(data.get("remember_secrets", True)))
        self.keep_identity.set(bool(data.get("keep_identity", True)))
        self.embed_cover.set(bool(data.get("embed_cover", True)))
        self.write_bpm_to_xml.set(bool(data.get("write_bpm_to_xml", True)))
        self.fill_missing.set(bool(data.get("fill_missing_only", False)))
        self.tag_first.set(bool(data.get("tag_first", False)))
        if data.get("delay") is not None:
            self.delay.delete(0, "end")
            self.delay.insert(0, str(data["delay"]))
        if data.get("rename_template"):
            self.rename_box.insert(0, str(data["rename_template"]))
        style = str(data.get("key_format") or "camelot")
        for label, key in _KEYS:
            if key == style:
                self.key_box.set(label)
        enabled = data.get("enabled_fields") if isinstance(data.get("enabled_fields"), dict) else {}
        for name, var in self.field_vars.items():
            if name in enabled:
                var.set(bool(enabled[name]))
        genre = data.get("genre_map") if isinstance(data.get("genre_map"), dict) else {}
        if not genre and isinstance(data.get("genre_map_text"), str):
            genre = parse_genre_map(data["genre_map_text"])
        for source, target in genre.items():
            self.genre_tree.insert("", "end", values=(source, target))
        self._paint_providers()

    def _persist(self) -> None:
        save_settings(
            {
                "folders": self.paths,
                "beatport_user": self.user.get().strip(),
                "beatport_password": self.password.get(),
                "spotify_client_id": self.spotify_id.get().strip(),
                "spotify_client_secret": self.spotify_secret.get(),
                "acoustid_key": self.acoustid.get().strip(),
                "grok_key": self.grok_key.get(),
                "gemini_key": self.gemini_key.get(),
                "remember_secrets": not self.forget_secrets.get(),
                "use_shazam": self.use_shazam.get(),
                "use_beatport": self.use_beatport.get(),
                "use_spotify": self.use_spotify.get(),
                "use_deezer": self.use_deezer.get(),
                "use_apple": self.use_apple.get(),
                "use_musicbrainz": self.use_musicbrainz.get(),
                "use_discogs": self.use_discogs.get(),
                "use_websearch": self.use_websearch.get(),
                "use_open_catalogs": True,
                "dry_run": True,
                "keep_identity": self.keep_identity.get(),
                "embed_cover": self.embed_cover.get(),
                "write_bpm_to_xml": self.write_bpm_to_xml.get(),
                "delay": self._delay_value(),
                "fill_missing_only": self.fill_missing.get(),
                "tag_first": self.tag_first.get(),
                "key_format": self._key_style(),
                "rename_template": self.rename_box.get().strip(),
                "enabled_fields": self._enabled_map(),
                "genre_map": self._genre_map(),
            }
        )

    def _paint_providers(self) -> None:
        marks = []
        for label, var in (
            ("Sh", self.use_shazam),
            ("Bp", self.use_beatport),
            ("Sp", self.use_spotify),
            ("Dz", self.use_deezer),
            ("Ap", self.use_apple),
            ("MB", self.use_musicbrainz),
            ("Di", self.use_discogs),
            ("Web", self.use_websearch),
        ):
            if var.get():
                marks.append(label)
        self.providers.configure(text="  ".join(marks))

    def _start(self) -> None:
        if self.worker and self.worker.is_alive():
            return
        if not self.paths:
            messagebox.showinfo("Music ID Tagger", "Húzz ide egy mappát, vagy adj hozzá fájlt.")
            return
        if not any(
            (
                self.use_shazam.get(),
                self.use_beatport.get(),
                self.use_spotify.get(),
                self.use_deezer.get(),
                self.use_apple.get(),
                self.use_musicbrainz.get(),
                self.use_discogs.get(),
                self.use_websearch.get(),
                bool(self.acoustid.get().strip()),
            )
        ):
            messagebox.showinfo("Music ID Tagger", "Kapcsolj be legalább egy forrást.")
            return
        self._persist()
        self._paint_providers()
        options = self._options()
        self.cancel = threading.Event()
        self.pending = []
        self._started = time.monotonic()
        for iid in self.tree.get_children():
            path = self.row_paths.get(iid, "")
            self.tree.item(iid, values=(Path(path).name if path else "", "Vár"), tags=("wait",))
        self.start_btn.configure(state="disabled")
        self.stop_btn.configure(state="normal")
        self._write("info", "Keresés indul. A fájlok ehhez a lépéshez még nem változnak.")
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
        self._write("muted", "Megállítás kérve. A folyamatban lévő fájl még befejeződik.")

    def _apply(self, mode: str) -> None:
        if self.worker and self.worker.is_alive():
            messagebox.showinfo("Music ID Tagger", "Előbb álljon meg a keresés.")
            return
        selected = [self.result_rows[iid] for iid in self.results.selection() if iid in self.result_rows]
        rows = select_for_apply(self.pending, mode, selected)
        if not rows:
            messagebox.showinfo("Music ID Tagger", "Nincs alkalmazható sor.")
            return
        self._persist()
        options = self._options()
        self.start_btn.configure(state="disabled")
        self.worker = threading.Thread(target=self._apply_work, args=(rows, options), daemon=True)
        self.worker.start()

    def _apply_work(self, rows: list[Pending], options: Options) -> None:
        from music_id_tagger.pending import apply_pending

        def log(level: str, text: str) -> None:
            self.queue.put(("log", level, text))

        try:
            count = apply_pending(rows, options, log, list(self.xmls))
        except Exception as exc:
            self.queue.put(("log", "err", f"Alkalmazás hiba: {exc}"))
            count = 0
        self.queue.put(("applied", count))

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
        tk.Label(dialog, text="Melyik futást állítsam vissza?", bg=BG, fg=INK, font=self._face(10)).pack(anchor="w", padx=12, pady=(12, 6))
        box = tk.Listbox(dialog, bg=ENTRY, fg=INK, selectbackground=BRASS, selectforeground=BG, highlightthickness=0, font=self._face(10))
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
                return messagebox.askyesno("Visszavonás", f"{path.name} megváltozott a címkézés óta. Visszaállítsam?", parent=dialog)

            revert(target, lambda level, text: self._write(level, text), confirm)
            dialog.destroy()

        self._button(dialog, "Kijelölt visszaállítása", go, BRASS).pack(pady=(0, 12))

    def _export_csv(self) -> None:
        from music_id_tagger.pending import export_csv

        if not self.pending:
            messagebox.showinfo("Music ID Tagger", "Még nincs eredmény.")
            return
        dest = filedialog.asksaveasfilename(title="CSV", defaultextension=".csv", filetypes=[("CSV", "*.csv")])
        if not dest:
            return
        only = self._filter_key()
        count = export_csv(self.pending, Path(dest), None if only == "all" else only)
        self._write("ok", f"CSV: {count} sor → {dest}")

    def _duplicates(self) -> None:
        from music_id_tagger.pending import duplicate_groups

        groups = duplicate_groups(self.pending)
        if not groups:
            messagebox.showinfo("Music ID Tagger", "Nincs közös ISRC vagy Beatport ID. Semmi nem törlődik.")
            return
        lines = []
        for group in groups:
            flag = " hossz eltér" if group["duration_mismatch"] else ""
            lines.append(f"{group['kind']} {group['value']}{flag}: {len(group['files'])} fájl")
        messagebox.showinfo("Duplikátumok", "\n".join(lines[:30]))

    def _filter_key(self) -> str:
        label = self.filter_box.get()
        for text, key in _FILTERS:
            if text == label:
                return key
        return "all"

    def _fill_results(self) -> None:
        for iid in self.results.get_children():
            self.results.delete(iid)
        self.result_rows.clear()
        for item in filter_pending(self.pending, self._filter_key()):
            tag = item.status if item.status in {"ok", "unsure", "missed", "failed", "applied"} else "ok"
            if item.unsure and item.status == "ok":
                tag = "unsure"
            label = "Bizonytalan" if item.unsure and item.status in {"ok", "unsure"} else _STATE.get(item.status, item.status)
            iid = self.results.insert(
                "",
                "end",
                values=(label, item.name, summary_line(item), item.source or "–", f"{item.confidence}%"),
                tags=(tag,),
            )
            self.result_rows[iid] = item.path
        self._show_detail()

    def _current(self) -> Pending | None:
        selected = self.results.selection()
        if not selected:
            return None
        path = self.result_rows.get(selected[0], "")
        for item in self.pending:
            if item.path == path:
                return item
        return None

    def _show_detail(self) -> None:
        for child in self.detail.winfo_children():
            child.destroy()
        item = self._current()
        if item is None:
            tk.Label(self.detail, text="Válassz egy sort.\nBizonytalannál dupla kattintás: találat választása.", bg=ENTRY, fg=MUTED, justify="left", font=self._face(10)).pack(anchor="w", padx=10, pady=10)
            return
        changes = preview_changes(item, self._enabled_map(), self.fill_missing.get(), self._key_style(), self._genre_map())
        tk.Label(self.detail, text=item.name, bg=ENTRY, fg=INK, font=self._face(11, True), wraplength=320, justify="left").pack(anchor="w", padx=10, pady=(8, 4))
        for name, label in _FIELDS:
            keys = FIELDS[name]
            old = " | ".join(str(item.before.get(key) or "") for key in keys if item.before.get(key))
            new = " | ".join(str(item.after.get(key) or "") for key in keys if item.after.get(key))
            changed = any(key in changes for key in keys)
            row = tk.Frame(self.detail, bg=ENTRY)
            row.pack(fill="x", padx=8, pady=1)
            var = tk.BooleanVar(value=field_enabled(name, self._enabled_map(), item.fields))

            def toggle(field=name, variable=var, current=item) -> None:
                current.fields[field] = bool(variable.get())
                self._refresh_result_row(current)

            tk.Checkbutton(row, variable=var, command=toggle, bg=ENTRY, fg=INK, selectcolor=PAPER, activebackground=ENTRY, highlightthickness=0).pack(side="left")
            tk.Label(row, text=label, bg=ENTRY, fg=BRASS if changed else MUTED, width=16, anchor="w", font=self._face(10, changed)).pack(side="left")
            tk.Label(row, text=f"{old or '–'} → {new or '–'}", bg=ENTRY, fg=INK if changed else MUTED, anchor="w", font=self._face(10)).pack(side="left", fill="x", expand=True)
        self.cover_label = tk.Label(self.detail, text="Borító: nincs előnézet", bg=ENTRY, fg=MUTED, font=self._face(10))
        self.cover_label.pack(anchor="w", padx=10, pady=(8, 4))
        url = str(item.after.get("cover_url") or item.before.get("cover_url") or "")
        if url.startswith("https://"):
            threading.Thread(target=self._load_cover, args=(url, item.path), daemon=True).start()
        if item.source_url.startswith("https://"):
            self._button(self.detail, item.source_label or "Forrás", lambda link=item.source_url: webbrowser.open(link), PAPER).pack(anchor="w", padx=10, pady=4)
        self._button(self.detail, "Találat választása…", self._pick, BRASS).pack(anchor="w", padx=10, pady=(4, 10))

    def _refresh_result_row(self, item: Pending) -> None:
        changes = preview_changes(item, self._enabled_map(), self.fill_missing.get(), self._key_style(), self._genre_map())
        item.changed = changes
        for iid, path in self.result_rows.items():
            if path == item.path and self.results.exists(iid):
                current = self.results.item(iid, "values")
                state = current[0] if current else ""
                self.results.item(iid, values=(state, item.name, summary_line(item), item.source or "–", f"{item.confidence}%"))
        self._show_detail()

    def _load_cover(self, url: str, path: str) -> None:
        try:
            import io

            import requests
            from PIL import Image, ImageTk
        except Exception:
            return
        try:
            response = requests.get(url, timeout=15)
            if response.status_code != 200 or not response.content:
                return
            image = Image.open(io.BytesIO(response.content))
            image.thumbnail((180, 180))
            photo = ImageTk.PhotoImage(image)
        except Exception:
            return

        def paint() -> None:
            current = self._current()
            if current is None or current.path != path:
                return
            self._cover_image = photo
            if getattr(self, "cover_label", None) is not None:
                self.cover_label.configure(image=photo, text="")

        try:
            self.after(0, paint)
        except Exception:
            return

    def _on_result_double(self, event) -> None:
        iid = self.results.identify_row(event.y)
        if not iid:
            return
        item = self._current()
        if item and (item.unsure or item.candidates or item.status in {"unsure", "missed"}):
            self._pick()

    def _pick(self) -> None:
        item = self._current()
        if item is None:
            return
        dialog = tk.Toplevel(self)
        dialog.title("Találat választása")
        dialog.configure(bg=BG)
        dialog.geometry("640x420")
        tk.Label(dialog, text=item.name, bg=BG, fg=INK, font=self._face(11, True)).pack(anchor="w", padx=12, pady=(12, 6))
        box = tk.Listbox(dialog, bg=ENTRY, fg=INK, selectbackground=BRASS, selectforeground=BG, highlightthickness=0, font=self._face(10))
        box.pack(fill="both", expand=True, padx=12, pady=(0, 8))
        for cand in item.candidates[:3]:
            bits = [str(cand.get("artist") or ""), str(cand.get("title") or ""), str(cand.get("mix") or "")]
            extra = " · ".join(part for part in (cand.get("bpm"), cand.get("key"), cand.get("genre")) if part)
            box.insert("end", " - ".join(part for part in bits if part) + (f"   {extra}" if extra else ""))
        if item.candidates:
            box.selection_set(0)
        manual = tk.Entry(dialog, bg=ENTRY, fg=INK, insertbackground=INK, relief="flat", font=self._face(10))
        manual.pack(fill="x", padx=12, pady=(0, 8), ipady=4)
        manual.insert(0, "")

        def use_listed() -> None:
            picked = box.curselection()
            if not picked:
                return
            from music_id_tagger.pending import choose_candidate

            choose_candidate(item, picked[0], self._key_style(), self._genre_map())
            self._fill_results()
            dialog.destroy()

        def use_manual() -> None:
            from music_id_tagger.beatport import parse_beatport_id

            ident = parse_beatport_id(manual.get())
            if not ident:
                messagebox.showinfo("Music ID Tagger", "Ez nem Beatport link vagy ID.", parent=dialog)
                return
            threading.Thread(target=self._manual_fetch, args=(item, ident, dialog), daemon=True).start()

        row = tk.Frame(dialog, bg=BG)
        row.pack(fill="x", padx=12, pady=(0, 12))
        self._button(row, "Kiválaszt", use_listed, BRASS).pack(side="left", padx=(0, 6))
        self._button(row, "Beatport link / ID", use_manual, PAPER).pack(side="left", padx=(0, 6))
        self._button(row, "Kihagy", dialog.destroy, CLAY).pack(side="left")

    def _manual_fetch(self, item: Pending, ident: str, dialog) -> None:
        from music_id_tagger.beatport import BeatportClient
        from music_id_tagger.pending import choose_candidate

        try:
            client = BeatportClient()
            client.login(self.user.get().strip(), self.password.get())
            meta = client.by_id(ident)
        except Exception as exc:
            message = str(exc)
            self.after(0, lambda message=message: messagebox.showerror("Music ID Tagger", message, parent=dialog))
            return
        if not meta:
            self.after(0, lambda: messagebox.showinfo("Music ID Tagger", "A Beatport nem adta vissza ezt az ID-t.", parent=dialog))
            return

        def apply_meta() -> None:
            item.candidates.append(meta)
            choose_candidate(item, len(item.candidates) - 1, self._key_style(), self._genre_map())
            self._fill_results()
            dialog.destroy()

        self.after(0, apply_meta)

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
                    self.progress_label.configure(text=f"{done} / {total} fájl")
                    self.eta_label.configure(text=eta_text(done, total, time.monotonic() - self._started))
                elif kind == "track":
                    self._track_row(item[1])
                elif kind == "done":
                    stats = item[1]
                    self.pending = list(stats.pending)
                    self.xmls = list(stats.xmls)
                    self.start_btn.configure(state="normal")
                    self.stop_btn.configure(state="disabled")
                    self._fill_results()
                    self.book_tabs.select(1)
                    if not stats.cancelled:
                        messagebox.showinfo(
                            "Music ID Tagger",
                            f"Keresés kész.\nBiztos vagy átnézendő: {stats.ok}\nNincs találat: {stats.missed}\nHiba: {stats.failed}\n\nAz Eredmények fülön nézd át, aztán alkalmazd.",
                        )
                elif kind == "applied":
                    self.start_btn.configure(state="normal")
                    self._fill_results()
                    self._write("ok", f"Alkalmazva: {item[1]} fájl.")
        except queue.Empty:
            pass
        self.after(120, self._drain)

    def _track_row(self, payload: dict) -> None:
        key = str(payload.get("path") or "")
        name = str(payload.get("name") or key)
        state = str(payload.get("state") or "wait")
        label = _STATE.get(state, state)
        tag = "bad" if state == "failed" else state if state in {"ok", "unsure", "missed", "run", "wait"} else "run"
        iid = self.rows.get(key)
        if iid and self.tree.exists(iid):
            self.tree.item(iid, values=(name, label), tags=(tag,))
            self.tree.see(iid)

    def _write(self, level: str, text: str) -> None:
        self.book.add(level, text)
        self._repaint_log()

    def _log_key(self) -> str:
        label = self.log_level.get()
        if label == "Hiba":
            return "err"
        if label == "Info":
            return "info"
        return "all"

    def _repaint_log(self) -> None:
        self.log.configure(state="normal")
        self.log.delete("1.0", "end")
        for level, text in self.book.filtered(self._log_key()):
            self.log.insert("end", text + "\n", level if level in {"ok", "err", "info", "muted"} else "muted")
        self.log.see("end")
        self.log.configure(state="disabled")

    def _copy_log(self) -> None:
        text = self.book.text(self._log_key())
        self.clipboard_clear()
        self.clipboard_append(text)
        self._write("muted", "A napló a vágólapon van.")

    def _save_log(self) -> None:
        dest = filedialog.asksaveasfilename(title="Napló", defaultextension=".txt", filetypes=[("Szöveg", "*.txt")])
        if not dest:
            return
        Path(dest).write_text(self.book.text(self._log_key()), encoding="utf-8")
        self._write("ok", f"Napló mentve: {dest}")

    def _check_update(self, manual: bool) -> None:
        if self._updating:
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
            if not messagebox.askyesno("Music ID Tagger", f"Van újabb verzió ({info['version']}). Letöltsem és elindítsam a telepítőt?"):
                return
            self._write("info", f"Frissítés letöltése: {info['version']}")
            threading.Thread(target=self._download_update, args=(info,), daemon=True).start()

        self.after(0, finish)

    def _download_update(self, info: dict) -> None:
        from music_id_tagger.updatecheck import fetch_verified, launch_installer

        try:
            dest = fetch_verified(str(info.get("url") or ""), str(info.get("sha256") or ""))
        except Exception as exc:
            message = str(exc)
            self.after(0, lambda message=message: messagebox.showerror("Music ID Tagger", message))
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
