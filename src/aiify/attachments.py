"""Files and text sent along with the next message.

Each attachment is saved in the agent's work folder and the agent is told its
path, so Claude and Codex read it (images included) with their own file tools.
Short text is also put in the message itself. An agent without file tools
(``access="app"``) gets every text file and image in the message instead.
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
INLINE_TEXT_ALL = 100_000        # text sent whole to an agent that cannot open files
IMAGE_TYPES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
               ".gif": "image/gif", ".webp": "image/webp"}
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


def _image_type(item: Attachment) -> str | None:
    return IMAGE_TYPES.get(item.path.suffix.lower())


def _contents(item: Attachment) -> str | None:
    """The attachment as text, or ``None`` for an image or binary file."""
    if item.text is not None:
        return item.text
    if _image_type(item):
        return None
    try:
        return item.path.read_bytes().decode("utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def attached_text(items: list[Attachment], *, readable: bool = True) -> str:
    """The message block naming each attachment's file (and short text in full).

    ``readable=False`` is for an agent without file tools (``access="app"``): text
    files go into the message whole, up to a limit, and images are sent with it."""
    if readable:
        lines = ["[Attached] Read these files when they matter to the request:"]
    else:
        lines = ["[Attached] You cannot open files; their text and images are in this message. "
                 "Pass a file's path to an app action that takes one."]
    for i in items:
        lines.append(f"- {i.name}: {i.path} ({max(1, i.size // 1024)} KB)")
        text = i.text if readable else _contents(i)
        if not readable and text is None:
            lines.append("  (image, sent with this message)" if _image_type(i) else
                         "  (not text or an image: only its path can be used)")
        elif text is not None and (len(text) <= INLINE_TEXT or not readable):
            cut = len(text) > INLINE_TEXT_ALL
            text = text[:INLINE_TEXT_ALL] + ("\n...(cut)" if cut else "")
            lines.append("  contents:\n" + "\n".join("    " + x for x in text.splitlines()))
    return "\n".join(lines)


def attached_images(items: list[Attachment]) -> list[tuple[str, str]]:
    """``(mime type, base64 data)`` for each attached image, to send with the message."""
    out = []
    for i in items:
        kind = _image_type(i)
        if kind:
            try:
                out.append((kind, base64.b64encode(i.path.read_bytes()).decode("ascii")))
            except OSError:
                pass
    return out
