"""Windows file drop for the Tk window. No-op anywhere else."""

from __future__ import annotations

import sys
from typing import Callable


def hook_dropfiles(widget, callback: Callable[[list[str]], None]) -> None:
    if sys.platform != "win32":
        return
    import ctypes
    from ctypes import wintypes

    hwnd = wintypes.HWND(widget.winfo_id())
    WM_DROPFILES = 0x0233
    GWLP_WNDPROC = -4
    LRESULT = ctypes.c_ssize_t
    WPARAM = ctypes.c_size_t
    LPARAM = ctypes.c_ssize_t
    prototype = ctypes.WINFUNCTYPE(LRESULT, wintypes.HWND, wintypes.UINT, WPARAM, LPARAM)

    user32 = ctypes.windll.user32
    shell32 = ctypes.windll.shell32
    user32.GetWindowLongPtrW.restype = ctypes.c_void_p
    user32.GetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.SetWindowLongPtrW.restype = ctypes.c_void_p
    user32.SetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_void_p]
    user32.CallWindowProcW.restype = LRESULT
    user32.CallWindowProcW.argtypes = [ctypes.c_void_p, wintypes.HWND, wintypes.UINT, WPARAM, LPARAM]
    shell32.DragAcceptFiles.argtypes = [wintypes.HWND, wintypes.BOOL]
    shell32.DragQueryFileW.argtypes = [wintypes.HANDLE, wintypes.UINT, wintypes.LPWSTR, wintypes.UINT]
    shell32.DragQueryFileW.restype = wintypes.UINT
    shell32.DragFinish.argtypes = [wintypes.HANDLE]

    previous = user32.GetWindowLongPtrW(hwnd, GWLP_WNDPROC)

    def handler(window, msg, wparam, lparam):
        if msg == WM_DROPFILES:
            count = shell32.DragQueryFileW(wparam, 0xFFFFFFFF, None, 0)
            paths: list[str] = []
            for index in range(count):
                length = shell32.DragQueryFileW(wparam, index, None, 0)
                buf = ctypes.create_unicode_buffer(length + 1)
                shell32.DragQueryFileW(wparam, index, buf, length + 1)
                if buf.value:
                    paths.append(buf.value)
            shell32.DragFinish(wparam)
            if paths:
                widget.after(0, lambda found=paths: callback(found))
            return 0
        return user32.CallWindowProcW(previous, window, msg, wparam, lparam)

    proc = prototype(handler)
    widget._drop_proc = proc
    user32.SetWindowLongPtrW(hwnd, GWLP_WNDPROC, ctypes.cast(proc, ctypes.c_void_p))
    shell32.DragAcceptFiles(hwnd, True)
