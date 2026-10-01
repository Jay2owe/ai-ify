"""Files and text sent along with the next message.

Each attachment is saved in the agent's work folder and the agent is told its
path, so Claude and Codex read it (images included) with their own file tools.
Short text is also put in the message itself.
"""
from __future__ import annotations

import base64
import re
import shutil
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

MAX_BYTES = 10 * 1024 * 1024
INLINE_TEXT = 4000
DATA_URL = re.compile(r"^data:([^;,]*)(;base64)?,(.*)$", re.S)


@dataclass
class Attachment:
    id: str
    name: str
    path: Path
    size: int
    text: str | None = None

    def to_dict(self) -> dict:
        return {"id": self.id, "name": self.name, "size": self.size}


def _safe(name: str) -> str:
    name = re.sub(r"[^\w.\- ]+", "_", Path(str(name or "attachment")).name).strip(" .")
    return name[:80] or "attachment"


def decode_data_url(url: str) -> bytes:
    m = DATA_URL.match(url or "")
    if not m:
        raise ValueError("not a data: URL")
    if m.group(2):
        return base64.b64decode(m.group(3), validate=False)
    from urllib.parse import unquote_to_bytes
    return unquote_to_bytes(m.group(3))


class Attachments:
    """What goes with the next message. ``folder()`` gives the agent's work folder."""

    def __init__(self, folder):
        self.folder = folder
        self.items: list[Attachment] = []

    def add(self, name: str, *, text: str | None = None, data: bytes | None = None,
            data_url: str | None = None, path: str | Path | None = None) -> Attachment:
        """Attach text, bytes, a ``data:`` URL (what a browser reads a file as) or a file on disk."""
        given = [x is not None for x in (text, data, data_url, path)]
        if sum(given) != 1:
            raise ValueError("give exactly one of text, data, data_url or path")
        if data_url is not None:
            data = decode_data_url(data_url)
        if text is not None:
            data = str(text).encode("utf-8")
        if path is not None:
            src = Path(path)
            if not src.is_file():
                raise ValueError(f"no such file: {src}")
            size = src.stat().st_size
        else:
            size = len(data)
        if size > MAX_BYTES:
            raise ValueError(f"{name} is {size // 1024} KB; the limit is {MAX_BYTES // (1024 * 1024)} MB")
        aid = "a-" + uuid.uuid4().hex[:8]
        dest_dir = Path(self.folder()) / "attachments"
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / f"{time.strftime('%Y%m%d-%H%M%S')}-{aid[2:]}-{_safe(name or (src.name if path else ''))}"
        if path is not None:
            shutil.copyfile(src, dest)
        else:
            dest.write_bytes(data)
        item = Attachment(aid, _safe(name or dest.name), dest, size, text if text is not None else None)
        self.items.append(item)
        return item

    def remove(self, item_id: str) -> bool:
        before = len(self.items)
        self.items = [i for i in self.items if i.id != item_id]
        return len(self.items) != before

    def take(self) -> list[Attachment]:
        items, self.items = self.items, []
        return items

    def put_back(self, items: list[Attachment]) -> None:
        self.items = list(items) + self.items

    def info(self) -> list[dict]:
        return [i.to_dict() for i in self.items]


def attached_text(items: list[Attachment]) -> str:
    """The message block naming each attachment's file (and short text in full)."""
    lines = ["[Attached] Read these files when they matter to the request:"]
    for i in items:
        lines.append(f"- {i.name}: {i.path} ({max(1, i.size // 1024)} KB)")
        if i.text is not None and len(i.text) <= INLINE_TEXT:
            lines.append("  contents:\n" + "\n".join("    " + x for x in i.text.splitlines()))
    return "\n".join(lines)
