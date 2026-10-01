"""Switch between saved Codex accounts with codex-profiles, never during a message.

Credentials stay with codex-profiles. Only the active account is asked for its
usage (``status``, never ``--all`` or ``--id``): querying an inactive slot can
invalidate its saved refresh token. Copied from ara's codex_accounts.py, written
against codex-profiles 0.3.0, whose ``--json`` is a global flag: ``list``/``status``
answer with data, ``load`` with ``{"command": ..., "success": true}``; a failure
exits non-zero with plain text.
"""
from __future__ import annotations

import json
import math
import re
import shutil
import subprocess
import time
from pathlib import Path
from typing import Callable

from .usage import LimitWindow


class ProfileError(Exception):
    pass


def executable() -> str | None:
    found = shutil.which("codex-profiles")
    if found and Path(found).suffix.lower() in (".cmd", ".ps1", ""):
        # run npm's native binary directly, so the timeout and exit code are its own
        base = Path(found).parent / "node_modules" / "codex-profiles"
        native = base / "node_modules" / "codex-profiles-win32-x64" / "bin" / "codex-profiles.exe"
        if native.is_file():
            return str(native)
    return found


def run_profile(*args: str) -> dict:
    exe = executable()
    if not exe:
        raise ProfileError("codex-profiles is not installed")
    try:
        result = subprocess.run([exe, *args, "--json"], stdin=subprocess.DEVNULL,
                                capture_output=True, text=True, encoding="utf-8", errors="replace",
                                timeout=20, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        data = json.loads(result.stdout)
    except subprocess.TimeoutExpired as exc:
        raise ProfileError("Codex account check timed out") from exc
    except (OSError, ValueError) as exc:
        raise ProfileError("Could not read Codex account information") from exc
    if result.returncode or not isinstance(data, dict) or data.get("error"):
        # raw helper errors can include authentication details; never pass them on
        raise ProfileError(f"Codex account {args[0]} failed; check its login")
    return data


def _profile(row: dict) -> dict:
    return {"id": str(row.get("id") or ""),
            "name": str(row.get("label") or row.get("email") or row.get("id") or "current account")}


def confirmed(result: dict) -> bool:
    return result.get("success") is True or result.get("ok") is True


def parse_usage(data: dict, now: float) -> list[LimitWindow]:
    """The active account's main allowance from ``codex-profiles status``."""
    raw = data.get("usage") or {}
    if data.get("error") or raw.get("state") != "ok":
        return []
    buckets = [b for b in raw.get("buckets", []) if isinstance(b, dict)]
    main = next((b for b in buckets if b.get("id") == "codex"), None) or {}
    out = []
    for key, kind in (("five_hour", "five_hour"), ("weekly", "seven_day")):
        w = main.get(key)
        if not isinstance(w, dict):                       # some plans have no weekly window
            continue
        try:
            left = float(w["left_percent"])
            reset = int(w.get("reset_at") or 0)
        except (KeyError, ValueError, TypeError):
            return []
        if not math.isfinite(left) or not 0 <= left <= 100:
            return []
        out.append(LimitWindow("codex", kind, (100 - left) / 100, reset or None, None, now))
    return out


class CodexAccounts:
    """The saved Codex accounts and which one is active."""

    def __init__(self, run: Callable[..., dict] = run_profile, clock: Callable[[], float] = time.time):
        self.run, self.clock = run, clock
        self.current: str | None = None
        self.choices: list[dict] = []
        self.error: str | None = None

    def refresh(self) -> dict:
        """Re-read the saved accounts (local; asks no account for anything)."""
        try:
            rows = self.run("list").get("profiles") or []
            self.choices = [_profile(r) for r in rows if r.get("id")]
            current = next((r for r in rows if r.get("is_current")), None)
            self.current = str(current["id"]) if current and current.get("id") else None
            self.error = None
        except ProfileError as exc:
            self.choices, self.current, self.error = [], None, str(exc)
        return self.info()

    def info(self) -> dict:
        return {"current": self.current, "choices": list(self.choices), "error": self.error}

    def switch(self, identity: str) -> dict:
        """Make ``identity`` the active account and check that it took."""
        identity = str(identity)
        if not re.fullmatch(r"[\w@.+-]+", identity, re.ASCII):
            raise ProfileError("Unsupported saved account identifier")
        if not any(c["id"] == identity for c in self.choices):
            self.refresh()
            if not any(c["id"] == identity for c in self.choices):
                raise ProfileError("No saved Codex account with that id")
        if not confirmed(self.run("load", "--id", identity)):
            raise ProfileError("Codex did not confirm the account switch")
        self.refresh()
        if self.current != identity:
            raise ProfileError("Codex account switch could not be verified")
        return next(c for c in self.choices if c["id"] == identity)

    def usage(self) -> list[LimitWindow]:
        """Limits of the active account only."""
        try:
            return parse_usage(self.run("status"), self.clock())
        except ProfileError:
            return []
