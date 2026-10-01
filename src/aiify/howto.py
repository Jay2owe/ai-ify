"""``aiify how "plain question"``: search everything known about the app.

A small ranked word search (BM25, the method most search engines start from)
over the app's actions and routes, its pages, the on-screen commands and
controls, the guide, the README, the app notes and the app map, if the
developer built one (see :mod:`aiify.appmap`). It needs no setup and no tokens;
each hit says how to use what it found.
"""
from __future__ import annotations

import hashlib
import math
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

MAP_NAME = "aiify_map.md"
SOURCE_SUFFIXES = {".py", ".js", ".ts", ".tsx", ".jsx", ".html", ".vue", ".svelte", ".md", ".qml", ".ui"}
SKIP_DIRS = {"__pycache__", ".git", "node_modules", ".venv", "venv", "build", "dist", ".pytest_cache",
             "vendor", ".mypy_cache", ".ruff_cache"}
MAX_FILE = 2 * 1024 * 1024
STOP = set("a an and are as at be by can do does for from get how i if in into is it its me my of on "
           "or so that the their them then there these this to use using want was we what when where "
           "which who why will with you your".split())
HEADER = re.compile(r"^<!-- aiify app map: (.*?) -->\s*$")


def words(text: str) -> list[str]:
    out = []
    for w in re.findall(r"[a-z0-9]+", str(text).lower().replace("_", " ")):
        if w in STOP or len(w) < 2:
            continue
        for end in ("ing", "ed", "es", "s"):
            if len(w) > len(end) + 3 and w.endswith(end):
                w = w[: -len(end)]
                break
        out.append(w)
    return out


@dataclass
class Entry:
    kind: str           # action, page, command, control, guide, docs, map, note
    title: str
    text: str
    use: str = ""


def sections(text: str, kind: str, use: str = "") -> list[Entry]:
    """Split Markdown at its headings; a heading's own text is the title."""
    out, title, buf = [], "", []
    for line in str(text or "").splitlines():
        m = re.match(r"^#{1,4}\s+(.*)$", line)
        if m:
            if "".join(buf).strip():
                out.append(Entry(kind, title or "(start)", "\n".join(buf).strip(), use))
            title, buf = m.group(1).strip(), []
        else:
            buf.append(line)
    if "".join(buf).strip():
        out.append(Entry(kind, title or "(start)", "\n".join(buf).strip(), use))
    return out


def search(entries: Iterable[Entry], question: str, limit: int = 8) -> list[tuple[float, Entry]]:
    """BM25 over title (counted three times) and text."""
    entries = list(entries)
    docs = [words(e.title) * 3 + words(e.text) for e in entries]
    query = list(dict.fromkeys(words(question)))
    if not docs or not query:
        return []
    n = len(docs)
    avg = sum(map(len, docs)) / n or 1.0
    df = Counter(w for d in docs for w in set(d))
    scored = []
    for e, d in zip(entries, docs):
        tf = Counter(d)
        score = 0.0
        for w in query:
            if tf[w]:
                idf = math.log(1 + (n - df[w] + 0.5) / (df[w] + 0.5))
                score += idf * tf[w] * 2.2 / (tf[w] + 1.2 * (0.25 + 0.75 * len(d) / avg))
        if score > 0:
            scored.append((score, e))
    scored.sort(key=lambda x: -x[0])
    return scored[:limit]


# -- the app map and the source it describes ---------------------------------------------
def source_files(root: Path, skip: Iterable[Path] = ()) -> list[Path]:
    skip = {Path(p).resolve() for p in skip}
    out = []
    for path in sorted(root.rglob("*")):
        rel = path.relative_to(root)
        if any(part in SKIP_DIRS or part.endswith(".egg-info") for part in rel.parts[:-1]):
            continue
        if path.is_file() and path.suffix.lower() in SOURCE_SUFFIXES and path.name != MAP_NAME \
                and path.resolve() not in skip and path.stat().st_size <= MAX_FILE:
            out.append(path)
    return out


def source_hash(root: Path) -> str:
    """A fingerprint of the app's source, to tell when a map is out of date."""
    h = hashlib.sha256()
    for path in source_files(root):
        h.update(path.relative_to(root).as_posix().encode())
        h.update(b"\0")
        h.update(path.read_bytes().replace(b"\r\n", b"\n"))
        h.update(b"\0")
    return h.hexdigest()[:16]


def read_header(text: str) -> dict:
    first = text.splitlines()[0] if text else ""
    m = HEADER.match(first)
    if not m:
        return {}
    return dict(part.split("=", 1) for part in m.group(1).split() if "=" in part)


class AppMap:
    """A map file the developer built with ``python -m aiify.appmap build``."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self.text = self.path.read_text(encoding="utf-8")
        self.header = read_header(self.text)
        self._fresh: bool | None = None

    @property
    def root(self) -> Path:
        return self.path.parent

    def fresh(self) -> bool:
        """Whether the source still matches what the map was built from (checked once)."""
        if self._fresh is None:
            self._fresh = self.header.get("sources") == source_hash(self.root)
        return self._fresh

    def overview(self, limit: int = 1500) -> str:
        for e in sections(self.text, "map"):
            if e.title.lower().startswith("overview"):
                return e.text[:limit]
        return ""

    def entries(self) -> list[Entry]:
        return [e for e in sections(self.text, "map") if e.title != "(start)"]


def find_map(dirs: Iterable[Path]) -> AppMap | None:
    for d in dirs:
        path = Path(d) / MAP_NAME
        if path.is_file():
            try:
                return AppMap(path)
            except OSError:
                continue
    return None


def readme_entries(dirs: Iterable[Path]) -> list[Entry]:
    """The README next to the app's package, or up to two folders up (a source checkout)."""
    for d in dirs:
        for folder in (Path(d), Path(d).parent, Path(d).parent.parent):
            for name in ("README.md", "README.rst", "README.txt"):
                path = folder / name
                if path.is_file() and path.stat().st_size <= MAX_FILE:
                    return sections(path.read_text(encoding="utf-8", errors="replace"), "docs")
    return []
