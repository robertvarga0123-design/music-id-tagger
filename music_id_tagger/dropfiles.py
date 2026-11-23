"""Windows file drop. Leaves Tk's own window procedure alone, so a drop cannot freeze the app."""

from __future__ import annotations

import sys
from typing import Callable


def hook_dropfiles(widget, callback: Callable[[list[str]], None]) -> None:
    if sys.platform != "win32":
        return
    import ctypes
    from ctypes import wintypes

    hwnd = widget.winfo_id()
    if not hwnd:
        return

    WM_DROPFILES = 0x0233
    shell32 = ctypes.windll.shell32
    comctl = ctypes.windll.comctl32

    shell32.DragQueryFileW.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_wchar_p, ctypes.c_uint]
    shell32.DragQueryFileW.restype = ctypes.c_uint
    shell32.DragFinish.argtypes = [ctypes.c_void_p]
    shell32.DragAcceptFiles.argtypes = [wintypes.HWND, wintypes.BOOL]

    prototype = ctypes.WINFUNCTYPE(
        ctypes.c_ssize_t,
        wintypes.HWND,
        wintypes.UINT,
        ctypes.c_size_t,
        ctypes.c_ssize_t,
        ctypes.c_size_t,
        ctypes.c_ssize_t,
    )
    comctl.SetWindowSubclass.argtypes = [wintypes.HWND, prototype, ctypes.c_size_t, ctypes.c_ssize_t]
    comctl.SetWindowSubclass.restype = wintypes.BOOL
    comctl.DefSubclassProc.argtypes = [wintypes.HWND, wintypes.UINT, ctypes.c_size_t, ctypes.c_ssize_t]
    comctl.DefSubclassProc.restype = ctypes.c_ssize_t

    def read_paths(handle) -> list[str]:
        count = shell32.DragQueryFileW(handle, 0xFFFFFFFF, None, 0)
        found: list[str] = []
        for index in range(int(count)):
            length = shell32.DragQueryFileW(handle, index, None, 0)
            buf = ctypes.create_unicode_buffer(int(length) + 1)
            shell32.DragQueryFileW(handle, index, buf, int(length) + 1)
            if buf.value:
                found.append(buf.value)
        return found

    def handler(window, msg, wparam, lparam, uid, data):
        if msg == WM_DROPFILES:
            paths: list[str] = []
            try:
                paths = read_paths(wparam)
            except Exception:
                paths = []
            try:
                shell32.DragFinish(wparam)
            except Exception:
                pass
            if paths:
                try:
                    widget.after(0, lambda found=list(paths): callback(found))
                except Exception:
                    pass
            return 0
        try:
            return comctl.DefSubclassProc(window, msg, wparam, lparam)
        except Exception:
            return 0

    proc = prototype(handler)
    widget._drop_proc = proc
    if not comctl.SetWindowSubclass(hwnd, proc, 1, 0):
        return
    shell32.DragAcceptFiles(hwnd, True)
