"""In-memory account window; no password widgets, terminal output or files."""

from __future__ import annotations

import sys
import time

from tests.rehearsals.programme_clipboard import PrivateClipboard


class CredentialWindow:
    """A local-only Windows recipient for the authenticated synthetic accounts."""

    def __init__(self):
        import tkinter as tk  # noqa: PLC0415 - optional desktop runtime
        from tkinter import ttk  # noqa: PLC0415

        self.root = tk.Tk()
        self.root.withdraw()
        self.root.title("Programme test accounts")
        self.root.minsize(560, 290)
        self.people = []
        self.deadline = None
        self.stop_requested = False
        self.failed = False
        self.status = tk.StringVar(value="Waiting for authenticated test accounts.")
        try:
            self.clipboard = PrivateClipboard(self.root.winfo_id())
        except Exception:
            self.root.destroy()
            raise
        self.root.report_callback_exception = self._callback_failed
        self.root.protocol("WM_DELETE_WINDOW", self.request_stop)
        frame = ttk.Frame(self.root, padding=20)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text="Fictional local test accounts").pack(anchor="w")
        ttk.Label(frame, text="Role").pack(anchor="w", pady=(15, 0))
        self.role = ttk.Combobox(frame, state="readonly", width=60)
        self.role.pack(fill="x")
        self.role.bind("<<ComboboxSelected>>", self._selected)
        self.email = tk.StringVar()
        ttk.Label(frame, textvariable=self.email).pack(anchor="w", pady=10)
        buttons = ttk.Frame(frame)
        buttons.pack(anchor="w")
        self.copy_email = ttk.Button(
            buttons, text="Copy email", command=lambda: self.copy("email")
        )
        self.copy_email.pack(side="left")
        self.copy_password = ttk.Button(
            buttons, text="Copy password", command=lambda: self.copy("password")
        )
        self.copy_password.pack(side="left", padx=10)
        ttk.Label(frame, textvariable=self.status, wraplength=520).pack(
            anchor="w", pady=15
        )
        ttk.Label(
            frame,
            text="Copies expire after 30 seconds. "
            "Paste only into this session's login.\n"
            "Closing this window stops the disposable session.",
        ).pack(anchor="w")

    def _callback_failed(self, *_error):
        # Tk's default callback handler writes a traceback to stderr. Never
        # forward account-bearing callback arguments or exception messages.
        self.failed = True
        self.request_stop()
        self.status.set("Account window failed. Stopping the test session.")

    def show_accounts(self, people):
        if self.stop_requested:
            return
        self.people = list(people)
        self.role.configure(values=[person["role"] for person in self.people])
        self.role.current(0)
        self._selected()
        self.root.deiconify()
        self.role.focus_set()

    def _selected(self, _event=None):
        self.expire_copy()
        self.email.set(self.people[self.role.current()]["email"])

    def copy(self, field):
        if self.stop_requested or field not in {"email", "password"}:
            return
        try:
            self.clipboard.copy(self.people[self.role.current()][field])
        except OSError:
            self.status.set("Copy failed. Close other clipboard tools and try again.")
            return
        self.deadline = time.monotonic() + 30
        self.status.set("Copied for 30 seconds; paste into the local test login now.")

    def expire_copy(self):
        try:
            self.clipboard.clear()
        except OSError:
            self.deadline = 0
            self.status.set("Clipboard busy; retrying cleanup. Do not paste elsewhere.")
            return False
        self.deadline = None
        self.status.set("Select an account, then copy its email or password.")
        return True

    def request_stop(self):
        self.stop_requested = True
        self.people.clear()
        self.copy_email.state(["disabled"])
        self.copy_password.state(["disabled"])
        self.role.configure(values=[], state="disabled")
        self.email.set("")
        if self.expire_copy():
            self.root.withdraw()

    def pump(self):
        if self.deadline is not None and time.monotonic() >= self.deadline:
            self.expire_copy()
        self.root.update()

    def close(self):
        self.request_stop()
        limit = time.monotonic() + 5
        while self.deadline is not None and time.monotonic() < limit:
            self.pump()
            time.sleep(0.05)
        self.root.destroy()
        if self.deadline is not None:
            sys.stderr.write(
                "Clipboard cleanup could not be confirmed. "
                "Copy harmless text manually before using another application.\n"
            )
            raise OSError("Clipboard cleanup failed; replace the clipboard manually.")
        if self.failed:
            raise OSError("Account window failed; no successful session is claimed.")
