"""Open the agent's conversation in a terminal window (the vendor CLI, resumed).

Copied from ara ``terminal.py`` (Windows Terminal, keep-open wrapper, launch) and
cut down. Sessions created through the ACP adapters resume in the vendor CLIs
(checked 2026-10-01: ``claude --resume <id>`` and ``codex resume <id>`` both
remembered a word set over ACP).
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Callable, Sequence

from .engine import child_env

SRC_ROOT = Path(__file__).resolve().parents[1]      # the folder holding the aiify package


def vendor_argv(provider: str, session_id: str) -> list[str]:
    """``claude --resume <id>`` / ``codex resume <id>``; raises if the CLI is missing."""
    exe = shutil.which(provider)
    if not exe:
        raise FileNotFoundError(f"the {provider} command is not on PATH, so no console can open")
    if provider == "claude":
        return [exe, "--resume", session_id]
    if provider == "codex":
        return [exe, "resume", session_id]
    raise ValueError(f"no console for provider {provider!r}")


def windows_terminal() -> str | None:
    found = shutil.which("wt.exe") or shutil.which("wt")
    if found:
        return found
    local = os.environ.get("LOCALAPPDATA")
    if local:
        candidate = os.path.join(local, "Microsoft", "WindowsApps", "wt.exe")
        if os.path.exists(candidate):
            return candidate
    return None


def console_python() -> str:
    """The interpreter with a console attached (an app may run under pythonw)."""
    py = sys.executable
    if py.lower().endswith("pythonw.exe"):
        py = py[: -len("pythonw.exe")] + "python.exe"
    return py


# Windows Terminal splits its command line on every unescaped ';' (a new-tab
# separator), even inside quotes, so the code handed to -c has none: statements
# are joined with \n escapes inside one exec string, and the package path travels
# as an ordinary argument.
KEEP_CODE = ("exec('import sys\\nsys.path.insert(0, sys.argv.pop(1))\\n"
             "from aiify.console import run_then_shell\\n"
             "sys.exit(run_then_shell(sys.argv[1:]))')")


def keep_open(argv: Sequence[str], note: str = "") -> list[str]:
    """``argv`` under a wrapper that outlives it, leaving ``note`` on screen.

    Windows Terminal runs the CLI as the tab's own process, so Ctrl+C would take
    the whole window with it. The wrapper starts the CLI from an argv list, so no
    shell parses it.
    """
    return [console_python(), "-X", "utf8", "-c", KEEP_CODE, str(SRC_ROOT),
            str(note or ""), "--"] + list(argv)


def run_then_shell(args: list[str]) -> int:
    """Inside the new window: run the CLI, print the note, then leave a shell open."""
    import signal

    note, argv = args[0], args[1:]
    if argv and argv[0] == "--":
        argv = argv[1:]
    try:
        signal.signal(signal.SIGINT, signal.SIG_IGN)
    except (ValueError, OSError, AttributeError):
        pass
    if argv:
        try:
            subprocess.call(argv)
        except OSError as exc:
            print(f"could not start {argv[0]}: {exc}")
    if note:
        print("\n" + note + "\n", flush=True)
    shell = os.environ.get("COMSPEC") or ("cmd.exe" if sys.platform == "win32" else "/bin/sh")
    try:
        return subprocess.call([shell])
    except OSError:
        input("press Enter to close ")
        return 0


def terminal_argv(cwd: str, argv: list[str], title: str = "", note: str = "") -> list[str]:
    """Wrap ``argv`` so it opens in a new terminal window at ``cwd``."""
    if sys.platform == "win32":
        wt = windows_terminal()
        if wt:
            out = [wt, "-d", cwd]
            if title:
                out += ["--title", title]
            return out + keep_open(argv, note)
        return ["cmd.exe", "/c", "start", title or "ai-ify", "/D", cwd] + keep_open(argv, note)
    for term in ("x-terminal-emulator", "gnome-terminal", "konsole", "xterm"):
        found = shutil.which(term)
        if found:
            return [found, "--" if term == "gnome-terminal" else "-e"] + list(argv)
    raise RuntimeError("no terminal emulator found")


def launch(argv: list[str], cwd: str) -> int | None:
    flags = 0
    if sys.platform == "win32" and argv and argv[0].lower().endswith("cmd.exe"):
        flags = subprocess.CREATE_NEW_CONSOLE
    proc = subprocess.Popen(argv, cwd=cwd, env=child_env(), creationflags=flags,
                            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL)
    return proc.pid


def open_console(provider: str, session_id: str, cwd: str, *, app: str = "",
                 launcher: Callable[[list[str], str], object] | None = None) -> list[str]:
    """Open the conversation in a new terminal; returns the argv used."""
    argv = vendor_argv(provider, session_id)
    note = (f"That was the {app or 'app'} conversation ({provider} session {session_id}). "
            f"Reopen it with: {Path(argv[0]).stem} {' '.join(argv[1:])}")
    full = terminal_argv(str(cwd), argv, title=f"{app or 'ai-ify'} - {provider}", note=note)
    (launcher or launch)(full, str(cwd))
    return full
