"""App notes: a small file the agent reads at the start of every chat and adds to
when the person asks it to remember something (``Agent(notes=True)``)."""
from __future__ import annotations

import threading
import time
from pathlib import Path

READ_LIMIT = 6000


class AppNotes:
    """Notes kept for one app across chats, one line each, in a Markdown file."""

    def __init__(self, path: Path | str):
        self.path = Path(path)
        self._lock = threading.Lock()

    def read(self) -> str:
        try:
            return self.path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return ""

    def add(self, text: str) -> str:
        line = " ".join(str(text or "").split())
        if not line:
            raise ValueError("empty note")
        entry = f"- {time.strftime('%Y-%m-%d')}: {line}\n"
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as fh:
                fh.write(entry)
        return entry.strip()

    def clear(self) -> None:
        with self._lock:
            self.path.unlink(missing_ok=True)

    def message_text(self, command: str) -> str:
        """The block told to the agent at the start of each chat."""
        text = self.read().strip()
        if len(text) > READ_LIMIT:
            text = "...(older notes cut)\n" + text[-READ_LIMIT:]
        return ("[App notes] Kept for this app across chats. When the person asks you to remember "
                "something, or states a lasting preference, save it as one short line with\n"
                f'  {command} notes.add text="..."\n'
                + (text or "(none yet)"))

    def register(self, port) -> None:
        async def read(req: dict) -> dict:
            return {"notes": self.read()}

        async def add(req: dict) -> dict:
            from .protocol import AiifyError
            try:
                return {"added": self.add(str(req.get("text") or ""))}
            except ValueError as exc:
                raise AiifyError("invalid", str(exc)) from exc

        port.register("notes.read", read)
        port.register("notes.add", add)
