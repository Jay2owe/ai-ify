"""Which actions a profile may run, and which need the person's approval first."""
from __future__ import annotations

from dataclasses import dataclass
from fnmatch import fnmatchcase
from typing import Iterable, Literal

Decision = Literal["run", "confirm", "deny"]


def _match(name: str, patterns: Iterable[str]) -> bool:
    return any(fnmatchcase(name, p) for p in patterns)


@dataclass(frozen=True)
class Policy:
    """``allow``: glob patterns the agent may run at all (default everything).
    ``confirm``: patterns that always ask first. Destructive actions always ask.
    ``deny``: patterns refused even when allowed."""
    allow: tuple[str, ...] = ("*",)
    confirm: tuple[str, ...] = ()
    deny: tuple[str, ...] = ()

    @classmethod
    def from_lists(cls, allow=None, confirm=None, deny=None) -> "Policy":
        return cls(tuple(allow) if allow is not None else ("*",),
                   tuple(confirm or ()), tuple(deny or ()))

    def check(self, name: str, spec: dict | None = None) -> Decision:
        if _match(name, self.deny) or not _match(name, self.allow):
            return "deny"
        if (spec or {}).get("destructive") or _match(name, self.confirm):
            return "confirm"
        return "run"

    def visible(self, name: str) -> bool:
        return self.check(name) != "deny"
