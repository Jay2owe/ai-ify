"""Message format helpers shared by the control port, the CLI and the web layer.

See docs/protocol.md. Everything that leaves the process goes through
:func:`serialize` so replies are always strict JSON.
"""
from __future__ import annotations

import dataclasses
import json
import math
import os
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any

PROTOCOL_VERSION = 1
MAX_LINE = 16 * 1024 * 1024

CODES = (
    "bad_token", "invalid", "unknown_op", "unknown_action", "denied",
    "requires_confirmation", "no_ui", "stale_ref", "not_found", "not_supported",
    "timeout", "failed",
)


class AiifyError(Exception):
    """An error that becomes an ``ok: false`` reply with a code."""

    def __init__(self, code: str, message: str, **extra: Any):
        super().__init__(message)
        self.code = code
        self.message = message
        self.extra = extra


@dataclasses.dataclass
class Reply:
    """A handler result with extra envelope fields (e.g. ``screen_changed``)."""
    result: Any = None
    extra: dict = dataclasses.field(default_factory=dict)


IMAGE_KEY = "aiify_image"
IMAGE_LIMIT = 8 * 1024 * 1024
IMAGE_TYPES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
               ".gif": "image/gif", ".webp": "image/webp"}


class ImageFile:
    """An image an action returns, such as a rendered preview.

    A full-access agent is given its path and opens it with its own tools; an
    app-only agent (``access="app"``) cannot open files, so the image itself goes
    with the tool result. The app's own code chooses which file: only images it
    returns this way are ever sent."""

    def __init__(self, path: str | Path):
        self.path = Path(path)

    def to_dict(self) -> dict:
        import base64
        out = {IMAGE_KEY: str(self.path)}
        mime = IMAGE_TYPES.get(self.path.suffix.lower())
        try:
            if mime is None:
                raise ValueError("not a PNG, JPEG, GIF or WebP image")
            if self.path.stat().st_size > IMAGE_LIMIT:
                raise ValueError(f"larger than {IMAGE_LIMIT // (1024 * 1024)} MB")
            out.update(mime_type=mime, data=base64.b64encode(self.path.read_bytes()).decode("ascii"))
        except (OSError, ValueError) as exc:
            out["error"] = str(exc)
        return out


def without_image_data(obj: Any) -> Any:
    """``obj`` with each :class:`ImageFile`'s data left out (for the ``aiify`` command)."""
    if isinstance(obj, dict):
        return {k: without_image_data(v) for k, v in obj.items()
                if not (k == "data" and IMAGE_KEY in obj)}
    if isinstance(obj, list):
        return [without_image_data(v) for v in obj]
    return obj


def serialize(obj: Any) -> Any:
    """Return strict JSON values, including dates, paths and records.

    Copied from ara's ``control.serialize`` and widened to fall back to
    ``str`` instead of raising, because a reply must never fail to encode.
    """
    if obj is None or isinstance(obj, (bool, int, str)):
        return obj
    if isinstance(obj, float):
        return obj if math.isfinite(obj) else None
    if isinstance(obj, (date, datetime)):
        return obj.isoformat()
    if isinstance(obj, Path):
        return str(obj)
    if isinstance(obj, dict):
        return {str(k): serialize(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, set, frozenset)):
        return [serialize(v) for v in obj]
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return {f.name: serialize(getattr(obj, f.name)) for f in dataclasses.fields(obj)}
    if callable(getattr(obj, "model_dump", None)):
        return serialize(obj.model_dump(mode="json", exclude_none=True, by_alias=True))
    if callable(getattr(obj, "to_dict", None)):
        return serialize(obj.to_dict())
    if hasattr(obj, "tolist"):                       # numpy scalars and arrays
        return serialize(obj.tolist())
    return str(obj)


def dumps(obj: Any, **kw) -> str:
    return json.dumps(serialize(obj), ensure_ascii=False, allow_nan=False, **kw)


def ok(rid: Any, result: Any = None, **extra: Any) -> dict:
    return {"id": rid, "ok": True, "result": serialize(result), **serialize(extra)}


def err(rid: Any, code: str, message: str, **extra: Any) -> dict:
    return {"id": rid, "ok": False, "code": code, "error": message, **serialize(extra)}


def home() -> Path:
    """The per-user ai-ify folder (registry, work folders), never a synced folder."""
    env = os.environ.get("AIIFY_HOME")
    if env:
        return Path(env)
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return Path(base) / "ai-ify"
    base = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return Path(base) / "ai-ify"


def registry_dir() -> Path:
    return home() / "apps"
