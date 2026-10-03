"""Windows clipboard boundary for deliberate, temporary synthetic login copies."""

from __future__ import annotations

import ctypes
import os
from contextlib import contextmanager
from ctypes import wintypes

_EXCLUSIONS = (
    "ExcludeClipboardContentFromMonitorProcessing",
    "CanIncludeInClipboardHistory",
    "CanUploadToCloudClipboard",
)


def _function(library, name, arguments, result):
    function = getattr(library, name)
    function.argtypes = arguments
    function.restype = result
    return function


class PrivateClipboard:
    """Never publish text unless Windows history/cloud exclusions are installed."""

    def __init__(self, window):
        if os.name != "nt":
            raise OSError("The hands-on account window requires Windows.")
        self.window = window
        self.sequence = None
        user = ctypes.WinDLL("user32", use_last_error=True)
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        self.open = _function(user, "OpenClipboard", [wintypes.HWND], wintypes.BOOL)
        self.close = _function(user, "CloseClipboard", [], wintypes.BOOL)
        self.empty = _function(user, "EmptyClipboard", [], wintypes.BOOL)
        self.owner = _function(user, "GetClipboardOwner", [], wintypes.HWND)
        self.serial = _function(user, "GetClipboardSequenceNumber", [], wintypes.DWORD)
        self.put = _function(
            user, "SetClipboardData", [wintypes.UINT, wintypes.HANDLE], wintypes.HANDLE
        )
        register = _function(
            user, "RegisterClipboardFormatW", [wintypes.LPCWSTR], wintypes.UINT
        )
        self.formats = tuple(register(name) for name in _EXCLUSIONS)
        if not all(self.formats):
            raise OSError("Clipboard privacy formats are unavailable.")
        self.allocate = _function(
            kernel, "GlobalAlloc", [wintypes.UINT, ctypes.c_size_t], wintypes.HGLOBAL
        )
        self.lock = _function(kernel, "GlobalLock", [wintypes.HGLOBAL], ctypes.c_void_p)
        self.unlock = _function(
            kernel, "GlobalUnlock", [wintypes.HGLOBAL], wintypes.BOOL
        )
        self.free = _function(
            kernel, "GlobalFree", [wintypes.HGLOBAL], wintypes.HGLOBAL
        )

    @contextmanager
    def opened(self):
        if not self.open(self.window):
            raise OSError("Clipboard busy; try again.")
        try:
            yield
        finally:
            self.close()

    def _put_bytes(self, format_id, payload):
        handle = self.allocate(2, len(payload))  # GMEM_MOVEABLE
        if not handle:
            raise OSError("Clipboard allocation failed.")
        transferred = False
        try:
            pointer = self.lock(handle)
            if not pointer:
                raise OSError("Clipboard allocation could not be locked.")
            try:
                ctypes.memmove(pointer, payload, len(payload))
            finally:
                self.unlock(handle)
            if not self.put(format_id, handle):
                raise OSError("Clipboard transfer failed.")
            transferred = True
        finally:
            # SetClipboardData takes ownership only on success.
            if not transferred:
                self.free(handle)

    def copy(self, value):
        with self.opened():
            if not self.empty():
                raise OSError("Clipboard could not be cleared.")
            self.sequence = None
            # These documented Windows formats precede CF_UNICODETEXT. There
            # is no ordinary clipboard fallback if any exclusion fails.
            for format_id in self.formats:
                self._put_bytes(format_id, bytes(4))
            self._put_bytes(13, (value + "\0").encode("utf-16-le"))
        # Closing finalizes Windows' synthesized formats and advances the
        # sequence. Record afterwards; clear still checks owner AND sequence
        # under its lock, preserving another application's intervening copy.
        self.sequence = self.serial()

    def clear(self):
        """Clear only our unchanged copy, checking ownership under the same lock."""
        if self.sequence is None:
            return
        with self.opened():
            if (
                self.owner() == self.window
                and self.serial() == self.sequence
                and not self.empty()
            ):
                raise OSError("Clipboard could not be cleared.")
            self.sequence = None
