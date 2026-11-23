# -*- mode: python ; coding: utf-8 -*-
"""Onedir build. shazamio_core native lib breaks inside a onefile exe."""

from PyInstaller.utils.hooks import collect_all, collect_submodules

packages = [
    "shazamio",
    "shazamio_core",
    "aiohttp",
    "aiohttp_retry",
    "pydantic",
    "pydantic_core",
    "mutagen",
    "requests",
    "PIL",
    "urllib3",
    "certifi",
    "idna",
    "charset_normalizer",
    "yarl",
    "multidict",
    "frozenlist",
    "aiosignal",
    "propcache",
    "attrs",
]

datas = []
binaries = []
hidden = [
    "music_id_tagger",
    "music_id_tagger.gui",
    "music_id_tagger.engine",
    "music_id_tagger.beatport",
    "music_id_tagger.spotify",
    "music_id_tagger.identify",
    "music_id_tagger.tags",
    "music_id_tagger.match",
    "music_id_tagger.config",
    "music_id_tagger.cli",
    "music_id_tagger.rekordbox",
    "music_id_tagger.dropfiles",
    "music_id_tagger.catalogs",
    "music_id_tagger.reconcile",
    "music_id_tagger.net",
    "music_id_tagger.covers",
    "music_id_tagger.undo",
    "acoustid",
    "musicbrainzngs",
]

for name in packages:
    try:
        package_datas, package_binaries, package_hidden = collect_all(name)
        datas += package_datas
        binaries += package_binaries
        hidden += package_hidden
    except Exception:
        try:
            hidden += collect_submodules(name)
        except Exception:
            hidden.append(name)

a = Analysis(
    ["app.py"],
    pathex=["."],
    binaries=binaries,
    datas=datas,
    hiddenimports=hidden,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["pytest", "tkinter.test"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="MusicIDTagger",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="MusicIDTagger",
)
