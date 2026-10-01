"""How an app configures its agent: profiles the person picks from, and rules
that add instructions when the app is in a given state."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Sequence

from .policy import Policy


@dataclass
class When:
    """Add ``add_instructions`` to a message whenever ``predicate(state)`` is true.

    ``When(lambda s: s.get("view") == "plots", "Plots are on screen; prefer plot.* actions.")``
    A predicate that raises counts as false.
    """
    predicate: Callable[[dict], bool]
    add_instructions: str
    name: str = ""

    def matches(self, state: dict) -> bool:
        try:
            return bool(self.predicate(state))
        except Exception:
            return False


@dataclass
class Profile:
    """One agent set-up the person can pick in the panel.

    ``model`` / ``effort`` / ``mode`` are starting values; the person can change
    them in the panel. ``None`` keeps the agent's own default. ``allow`` /
    ``confirm`` / ``deny`` are glob patterns over action names (see Policy).
    ``instructions`` is text, or a function of the app state returning text.
    """
    provider: str = "claude"
    model: str | None = None
    effort: str | None = None
    mode: str | None = None
    allow: Sequence[str] = ("*",)
    confirm: Sequence[str] = ()
    deny: Sequence[str] = ()
    instructions: str | Callable[[dict], str] = ""
    rules: Sequence[When] = field(default_factory=tuple)
    label: str = ""

    def policy(self) -> Policy:
        return Policy.from_lists(self.allow, self.confirm, self.deny)

    def settings(self) -> dict:
        return {k: v for k, v in (("model", self.model), ("effort", self.effort), ("mode", self.mode)) if v}

    def instructions_for(self, state: dict) -> str:
        if callable(self.instructions):
            try:
                return str(self.instructions(state) or "")
            except Exception as exc:
                return f"(the app's instructions could not be built: {exc})"
        return self.instructions or ""
