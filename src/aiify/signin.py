"""A vendor CLI's own sign-in, run without a terminal window.

Claude's ``auth login`` opens the browser, prints the sign-in link and waits for
either the browser to finish or a pasted code. Run hidden, its link goes to the
panel (in case the browser page opened behind other windows) and a code typed in
the panel goes to its input.
"""
from __future__ import annotations

import asyncio
import re
import shutil
import subprocess
from typing import Callable

from .engine import child_env, kill_tree

# OSC 8 hyperlinks (ESC ] 8 ; ; URL ESC \) and colour codes around the printed link
ESCAPES = re.compile(r"\x1b\]8;;[^\x1b\x07]*(?:\x1b\\|\x07)|\x1b\[[0-9;?]*[A-Za-z]")
LINK = re.compile(r"https://[^\s\x1b\x07]+")


def find_link(text: str) -> str | None:
    """The first complete https link in the output (something must follow it)."""
    plain = ESCAPES.sub("", text)
    found = LINK.search(plain)
    return found.group(0) if found and found.end() < len(plain) else None


class LoginProcess:
    """``argv`` (e.g. ``claude auth login --claudeai``) with no window.

    ``on_link(url)`` is called once with the sign-in link it prints.
    """

    def __init__(self, argv: list[str], *, cwd: str, on_link: Callable[[str], None]):
        self.argv = argv
        self.cwd = cwd
        self.on_link = on_link
        self.link: str | None = None
        self.output = ""
        self._proc: asyncio.subprocess.Process | None = None

    async def start(self) -> None:
        exe = shutil.which(self.argv[0]) or self.argv[0]
        self._proc = await asyncio.create_subprocess_exec(
            exe, *self.argv[1:], cwd=self.cwd, env=child_env(), stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))

    async def wait(self) -> int:
        """Read its output until it exits; returns the exit code (0 = signed in)."""
        assert self._proc is not None and self._proc.stdout is not None
        while True:
            chunk = await self._proc.stdout.read(4096)    # the code prompt has no newline
            if not chunk:
                break
            self.output = (self.output + chunk.decode("utf-8", "replace"))[-20000:]
            if self.link is None:
                self.link = find_link(self.output)
                if self.link:
                    self.on_link(self.link)
        return await self._proc.wait()

    async def send_code(self, code: str) -> None:
        if self._proc is None or self._proc.stdin is None or self._proc.returncode is not None:
            raise RuntimeError("the sign-in has already ended")
        self._proc.stdin.write((code.strip() + "\n").encode())
        await self._proc.stdin.drain()

    def stop(self) -> None:
        if self._proc is not None and self._proc.returncode is None:
            kill_tree(self._proc.pid)
