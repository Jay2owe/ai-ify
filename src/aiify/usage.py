"""How full each subscription limit is, read from what the agents already report.

Claude: some ACP ``usage_update`` events carry ``_meta["_claude/rateLimit"]`` for
the window that matters now; the adapter drops it in many turns, so the full set
comes from Claude Code's local ``/usage`` command, run in a separate throwaway
session (no model call, no tokens) and read from its markdown. Codex: its
session rollouts under ``$CODEX_HOME/sessions/Y/M/D/rollout-*.jsonl`` hold
``rate_limits`` records. Nothing is fetched from the network, so a reading is as
fresh as the last message. Both formats drift between releases: anything
unexpected is skipped, never fatal. Parsing copied from ara's usage.py.
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

LABELS = {"five_hour": "5h", "seven_day": "week", "seven_day_opus": "Opus week",
          "seven_day_sonnet": "Sonnet week", "seven_day_overage_included": "Fable week"}
ORDER = list(LABELS)
WARN_AT = 0.9                                  # bars turn to a warning at this fraction used
_TAIL = 256 * 1024
_cache: dict[str, tuple[float, int, dict | None]] = {}      # path -> (mtime, size, parsed)


@dataclass
class LimitWindow:
    provider: str
    kind: str                                  # five_hour | seven_day | seven_day_<model>
    used: float | None                         # 0-1; None when only a status is known
    resets_at: float | None                    # epoch seconds
    status: str | None = None                  # Claude: allowed | allowed_warning | rejected
    seen: float = 0.0                          # when the reading was taken
    label: str | None = None

    def to_dict(self, now: float, warn_at: float = WARN_AT) -> dict:
        expired = bool(self.resets_at) and self.resets_at <= now
        used = 0.0 if expired else self.used
        label = self.label or LABELS.get(self.kind, self.kind.replace("_", " "))
        return {"kind": self.kind, "label": label,
                "used": None if used is None else round(used * 100, 1),
                "resets_at": _iso(self.resets_at), "expired": expired,
                "resets_in_s": max(0, int(self.resets_at - now)) if self.resets_at else None,
                "status": self.status,
                "warn": not expired and ((used is not None and used >= warn_at)
                                         or self.status == "rejected")}


def _iso(epoch: float | None) -> str | None:
    if not epoch:
        return None
    return datetime.fromtimestamp(float(epoch)).strftime("%Y-%m-%dT%H:%M:%S")


def _num(value) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


# -- Claude ------------------------------------------------------------------------------

def claude_from_meta(meta: dict | None, now: float | None = None) -> list[LimitWindow]:
    """Windows in one ``usage_update`` ``_meta`` (or the rate-limit dict itself).

    ``{"_claude/rateLimit": {"status": "allowed_warning", "resetsAt": 1791090000,
    "rateLimitType": "seven_day", "utilization": 0.87}}``
    """
    now = time.time() if now is None else now
    if not isinstance(meta, dict):
        return []
    info = meta.get("_claude/rateLimit", meta)
    if not isinstance(info, dict):
        return []
    out: list[LimitWindow] = []
    windows = info.get("unifiedWindows")                  # the CLI's stream-json shape
    if isinstance(windows, dict):
        for kind, w in windows.items():
            if isinstance(w, dict) and _num(w.get("utilization")) is not None:
                out.append(LimitWindow("claude", kind, _num(w["utilization"]),
                                       _num(w.get("resetsAt")) or None, info.get("status"), now))
    kind = info.get("rateLimitType")
    if not out and isinstance(kind, str) and kind:
        out.append(LimitWindow("claude", kind, _num(info.get("utilization")),
                               _num(info.get("resetsAt")) or None, info.get("status"), now))
    return out


_LIMIT_LINE = re.compile(r"^\*\*(?P<label>[^*]+)\*\*\s*\W+\s*\*\*(?P<pct>\d+(?:\.\d+)?)%\*\*(?P<rest>.*)$")
_RESETS = re.compile(r"Resets\s+(?:(?P<mon>[A-Z][a-z]{2})[a-z]*\.?\s+(?P<day>\d{1,2}),?\s+)?"
                     r"(?P<h>\d{1,2})(?::(?P<m>\d{2}))?\s*(?P<ampm>[AP]M)?"
                     r"(?:\s*(?:GMT|UTC)(?P<tz>[+-]\d{1,2}(?::?\d{2})?)?)?", re.I)
_MONTHS = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"]


def _usage_kind(label: str) -> tuple[str, str]:
    """``5-hour limit`` -> five_hour; ``Weekly · all models`` -> seven_day; ``Weekly · Fable`` -> seven_day_fable."""
    low = label.lower()
    if "5-hour" in low or "five" in low or "session" in low:
        return "five_hour", "5h"
    if "week" in low:
        scope = re.split(r"[·:-]", label, maxsplit=1)[1].strip() if re.search(r"[·:-]", label) else ""
        if not scope or scope.lower() == "all models":
            return "seven_day", "week"
        return "seven_day_" + re.sub(r"\W+", "_", scope.lower()).strip("_"), f"{scope} week"
    return re.sub(r"\W+", "_", low).strip("_"), label


def _reset_epoch(text: str, now: float) -> float | None:
    m = _RESETS.search(text)
    if not m:
        return None
    try:
        hour, minute = int(m["h"]), int(m["m"] or 0)
        if m["ampm"]:
            hour = hour % 12 + (12 if m["ampm"].upper() == "PM" else 0)
        if m["tz"]:
            sign = -1 if m["tz"].startswith("-") else 1
            hh, _, mm = m["tz"][1:].partition(":")
            if not mm and len(hh) > 2:
                hh, mm = hh[:-2], hh[-2:]
            tz = timezone(sign * timedelta(hours=int(hh), minutes=int(mm or 0)))
        else:
            tz = datetime.now().astimezone().tzinfo
        base = datetime.fromtimestamp(now, tz)
        if m["mon"]:
            when = base.replace(month=_MONTHS.index(m["mon"][:3].lower()) + 1, day=int(m["day"]),
                                hour=hour, minute=minute, second=0, microsecond=0)
            if when.timestamp() < now - 2 * 86400:          # a date early next year
                when = when.replace(year=when.year + 1)
        else:
            when = base.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if when.timestamp() < now:
                when += timedelta(days=1)
        return when.timestamp()
    except (ValueError, IndexError):
        return None


def claude_from_usage_text(text: str, now: float | None = None) -> list[LimitWindow]:
    """The limit lines of Claude Code's ``/usage`` output, e.g.
    ``**Weekly · all models** — **90%** · Resets Oct 4, 5:59 AM GMT+1``."""
    now = time.time() if now is None else now
    out: list[LimitWindow] = []
    for line in (text or "").splitlines():
        m = _LIMIT_LINE.match(line.strip())
        if not m:
            continue
        kind, label = _usage_kind(m["label"].strip())
        out.append(LimitWindow("claude", kind, float(m["pct"]) / 100, _reset_epoch(m["rest"], now),
                               None, now, label))
    return out


async def check_claude_usage(cwd: Path | str, argv: list[str] | None = None,
                             timeout: float = 60) -> list[LimitWindow]:
    """Run ``/usage`` in a throwaway Claude session and read its limit lines."""
    import asyncio
    from .engine import AcpSession
    events: list[dict] = []
    session = AcpSession("claude", cwd=cwd, on_event=events.append, argv=argv)
    try:
        await asyncio.wait_for(session.start(), timeout)
        await asyncio.wait_for(session.send("/usage"), timeout)
    except Exception:                                      # noqa: BLE001 - limits are best effort
        return []
    finally:
        await session.close()
    return claude_from_usage_text("".join(e.get("text", "") for e in events if e.get("kind") == "text"))


# -- Codex -------------------------------------------------------------------------------

def _tail_lines(path: Path) -> list[str]:
    size = path.stat().st_size
    with path.open("rb") as fh:
        if size > _TAIL:
            fh.seek(size - _TAIL)
        data = fh.read()
    lines = data.decode("utf-8", "replace").splitlines()
    if size > _TAIL and lines:
        lines = lines[1:]                                   # the first line is a fragment
    return lines


def _cached(path: Path, parse: Callable[[list[str]], dict | None]) -> dict | None:
    try:
        st = path.stat()
    except OSError:
        return None
    key = str(path)
    hit = _cache.get(key)
    if hit and hit[0] == st.st_mtime and hit[1] == st.st_size:
        return hit[2]
    try:
        parsed = parse(_tail_lines(path))
    except OSError:
        parsed = None
    if parsed is not None and "seen" not in parsed:
        parsed["seen"] = st.st_mtime
    _cache[key] = (st.st_mtime, st.st_size, parsed)
    return parsed


def _newest(paths: list[Path], limit: int) -> list[Path]:
    def mtime(p: Path) -> float:
        try:
            return p.stat().st_mtime
        except OSError:
            return 0.0
    return sorted(paths, key=mtime, reverse=True)[:limit]


def parse_codex(lines: list[str]) -> dict | None:
    """Last ``rate_limits`` record in a Codex rollout."""
    for raw in reversed(lines):
        if '"rate_limits"' not in raw:
            continue
        try:
            obj = json.loads(raw)
        except json.JSONDecodeError:
            continue
        payload = obj.get("payload") if isinstance(obj.get("payload"), dict) else obj
        limits = payload.get("rate_limits") if isinstance(payload, dict) else None
        if not isinstance(limits, dict):
            continue
        out: dict[str, dict] = {}
        for key in ("primary", "secondary"):
            w = limits.get(key)
            if not isinstance(w, dict) or _num(w.get("used_percent")) is None:
                continue
            minutes = int(_num(w.get("window_minutes")) or 0)
            name = "five_hour" if 0 < minutes <= 600 else "seven_day"
            out[name] = {"pct": float(w["used_percent"]), "resets_at": int(_num(w.get("resets_at")) or 0)}
        if not out:
            continue
        found: dict = {"windows": out, "pool": limits.get("limit_id") or "codex"}
        stamp = (obj.get("timestamp") if isinstance(obj, dict) else None)
        if isinstance(stamp, str):
            try:
                found["seen"] = datetime.fromisoformat(stamp.replace("Z", "+00:00")).timestamp()
            except ValueError:
                pass
        return found
    return None


def codex_home() -> Path:
    return Path(os.environ.get("CODEX_HOME") or (Path.home() / ".codex"))


def codex_from_rollouts(home: Path | str | None = None, *, limit: int = 12) -> list[LimitWindow]:
    """The newest reading of Codex's main allowance pool from its session rollouts."""
    sessions = Path(home or codex_home()) / "sessions"
    if not sessions.is_dir():
        return []
    days = [d for d in sessions.glob("*/*/*") if d.is_dir()]
    files: list[Path] = []
    for day in _newest(days, 4):
        files.extend(day.glob("rollout-*.jsonl"))
    pools: dict[str, dict] = {}
    for path in _newest(files, limit):
        found = _cached(path, parse_codex)
        if found:
            pools.setdefault(found.get("pool") or "codex", found)
    found = pools.get("codex") or next(iter(pools.values()), None)
    if not found:
        return []
    return [LimitWindow("codex", kind, w["pct"] / 100, w["resets_at"] or None, None, found.get("seen") or 0)
            for kind, w in found["windows"].items()]


# -- what the panel shows -------------------------------------------------------------------

class UsageTracker:
    """Latest reading per provider and window; ``snapshot()`` is what the panel draws."""

    def __init__(self, warn_at: float = WARN_AT, codex_dir: Path | str | None = None):
        self.warn_at = warn_at
        self.codex_dir = codex_dir
        self.windows: dict[str, dict[str, LimitWindow]] = {}
        self.not_before: dict[str, float] = {}          # readings older than an account switch
        self._lock = threading.Lock()

    def update(self, windows: list[LimitWindow]) -> bool:
        changed = False
        with self._lock:
            for w in windows:
                if w.seen and w.seen < self.not_before.get(w.provider, 0):
                    continue                            # belongs to the account that was left
                have = self.windows.setdefault(w.provider, {})
                old = have.get(w.kind)
                if old is None or (old.used, old.resets_at, old.status) != (w.used, w.resets_at, w.status):
                    changed = True
                have[w.kind] = w
        return changed

    def from_usage_event(self, usage: dict | None) -> bool:
        meta = (usage or {}).get("_meta") or (usage or {}).get("field_meta")
        return self.update(claude_from_meta(meta)) if meta else False

    def refresh_codex(self) -> bool:
        return self.update(codex_from_rollouts(self.codex_dir))

    def forget(self, provider: str, *, since: float | None = None) -> None:
        """A different account is now in use: drop its readings and ignore older ones."""
        with self._lock:
            self.windows.pop(provider, None)
            self.not_before[provider] = time.time() if since is None else since

    def snapshot(self, now: float | None = None) -> dict:
        now = time.time() if now is None else now
        with self._lock:
            out = {}
            for provider, have in self.windows.items():
                ordered = sorted(have.values(), key=lambda w: ORDER.index(w.kind) if w.kind in ORDER else 99)
                out[provider] = [w.to_dict(now, self.warn_at) for w in ordered]
        return {"warn_at": self.warn_at, "providers": out}
