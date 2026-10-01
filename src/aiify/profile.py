"""How an app configures its agent: profiles the person picks from, rules that
add context to a message, and launches that start the chat from the app's buttons."""
from __future__ import annotations

import fnmatch
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, Sequence, Union

from .policy import Policy

Text = Union[str, Callable[["Turn"], "str | None"]]
Suggestions = Union[Sequence[Union[str, dict]], Callable[["Turn"], Sequence[Union[str, dict]]]]
ROLES = ("profile", "provider", "model", "effort", "mode")


@dataclass
class Turn:
    """One message from the person, as the app's context functions see it.

    ``text``: what they typed. ``state``: what the app shows now. ``provider``,
    ``model``, ``effort``, ``mode``: the agent's settings for this message.
    ``profile``: the profile in use. ``launch`` / ``data``: the launch that started
    this chat (a button in the app) and the data it passed. ``first``: whether this
    is the chat's first message.
    """
    text: str = ""
    state: dict = field(default_factory=dict)
    provider: str = ""
    model: str | None = None
    effort: str | None = None
    mode: str | None = None
    profile: str = ""
    launch: str | None = None
    data: Any = None
    first: bool = False


def resolve(text: Text, turn: Turn, what: str = "context") -> str:
    """Text as given, or the result of calling it with the turn; a failure is reported in the text."""
    if callable(text):
        try:
            out = text(turn)
        except Exception as exc:                          # noqa: BLE001 - the agent sees what failed
            return f"(the app's {what} could not be built: {type(exc).__name__}: {exc})"
        return "" if out is None else str(out)
    return str(text or "")


def suggestion_list(given: Suggestions, turn: "Turn") -> list[dict]:
    """``[{label, text}]`` from text, ``{label, text}`` dicts, or a function of the Turn."""
    if callable(given):
        given = given(turn)
    out = []
    for item in given or ():
        if isinstance(item, str) and item.strip():
            out.append({"label": item.strip(), "text": item.strip()})
        elif isinstance(item, dict) and str(item.get("text") or "").strip():
            text = str(item["text"]).strip()
            out.append({"label": str(item.get("label") or text), "text": text})
    return out[:8]


def allowed(value: str | None, patterns: Sequence[str] | str | None) -> bool:
    """Whether a picker value matches one of the glob patterns (no patterns: any value)."""
    if patterns is None:
        return True
    return _glob(patterns, value)


@dataclass
class Answer:
    """Returned by ``before_send``: reply to the person with this text, from the app,
    without sending the message to the agent."""
    text: str


@dataclass
class AgentReply:
    """What ``after_reply`` receives with the Turn: the reply's text, why it stopped
    (``end_turn``, ``cancelled``, ``error: ...``), tool calls and seconds taken."""
    text: str
    stop: str
    tools: int = 0
    total: float | None = None


def _prompt_matcher(prompt) -> Callable[[str], bool] | None:
    if prompt is None:
        return None
    if callable(prompt) and not isinstance(prompt, re.Pattern):
        return prompt
    if isinstance(prompt, re.Pattern):
        return lambda text: bool(prompt.search(text))
    words = [prompt] if isinstance(prompt, str) else list(prompt)
    found = re.compile("|".join(rf"\b{re.escape(w)}" for w in words), re.I)
    return lambda text: bool(found.search(text))


def _glob(pattern: str | Sequence[str] | None, value: str | None) -> bool:
    if pattern is None:
        return True
    patterns = [pattern] if isinstance(pattern, str) else list(pattern)
    return value is not None and any(fnmatch.fnmatchcase(str(value).lower(), p.lower()) for p in patterns)


@dataclass
class When:
    """Add context to a message when every condition given holds.

    ``When(lambda s: s.get("view") == "plots", "Plots are on screen; prefer plot.* actions.")``
    ``When(prompt="cost", add_instructions=lambda turn: price_note())``
    ``When(model="opus*", effort="high", add_instructions="Go deep.")``
    ``When(add_instructions=lambda turn: my_context(turn))``   (no condition: every message)

    ``predicate(state)``: a test of the app state. ``prompt``: a word (matches words
    starting with it, any case), a list of words, a compiled regex, or a function of
    the typed text. ``model`` / ``effort`` / ``provider`` / ``profile`` / ``launch``:
    a name or glob pattern, or a list of them. ``add_instructions``: text, or a
    function of the :class:`Turn` returning text (None or "" adds nothing).
    A predicate or prompt function that raises counts as false.
    """
    predicate: Callable[[dict], bool] | None = None
    add_instructions: Text = ""
    name: str = ""
    prompt: Any = None
    model: str | Sequence[str] | None = None
    effort: str | Sequence[str] | None = None
    provider: str | Sequence[str] | None = None
    profile: str | Sequence[str] | None = None
    launch: str | Sequence[str] | None = None

    def __post_init__(self):
        self._prompt = _prompt_matcher(self.prompt)

    def matches(self, turn: "Turn | dict") -> bool:
        if isinstance(turn, dict):                        # older callers pass the state alone
            turn = Turn(state=turn)
        try:
            if self.predicate is not None and not self.predicate(turn.state):
                return False
            if self._prompt is not None and not self._prompt(turn.text):
                return False
        except Exception:
            return False
        return (_glob(self.model, turn.model) and _glob(self.effort, turn.effort)
                and _glob(self.provider, turn.provider) and _glob(self.profile, turn.profile)
                and _glob(self.launch, turn.launch))

    def text_for(self, turn: Turn) -> str:
        return resolve(self.add_instructions, turn, f"rule {self.name or ''}".strip())


@dataclass
class Launch:
    """A way into the assistant from a button in the app, with its own context.

    The page starts it with ``aiify.launch(name, data)`` or a button carrying
    ``data-aiify-launch="name"`` (and optionally ``data-aiify-data='{"json": 1}'``).
    The panel opens and, by default, a new chat starts with this launch's set-up:

    ``profile``: a profile name to switch to. ``model`` / ``effort`` / ``mode``:
    settings for this chat. ``instructions``: text, or a function of the Turn,
    told to the agent at the start of the chat. ``rules``: When rules that apply
    only to this chat. ``message``: text (or a function of the Turn) sent at once
    as if the person typed it; leave it empty to let them type. ``new_chat``:
    False keeps the current conversation and adds this launch's context to it.
    ``suggestions``, ``lock``, ``limit``: as on :class:`Profile`, while this
    launch's chat lasts (a launch's take the place of the profile's).
    """
    label: str = ""
    profile: str | None = None
    model: str | None = None
    effort: str | None = None
    mode: str | None = None
    instructions: Text = ""
    rules: Sequence[When] = field(default_factory=tuple)
    message: Text = ""
    new_chat: bool = True
    suggestions: Suggestions = ()
    lock: Sequence[str] = ()
    limit: Mapping[str, Sequence[str]] = field(default_factory=dict)

    def __post_init__(self):
        _check_roles(self.lock, self.limit)


@dataclass
class Profile:
    """One agent set-up the person can pick in the panel.

    ``model`` / ``effort`` / ``mode`` are starting values; the person can change
    them in the panel. ``None`` keeps the agent's own default. ``allow`` /
    ``confirm`` / ``deny`` are glob patterns over action names (see Policy).
    ``instructions`` is text, or a function of the app state returning text.
    ``suggestions``: prompts offered as buttons in an empty chat (text, ``{label,
    text}``, or a function of the Turn returning them). ``lock``: pickers the
    person may not change (``"model"``, ``"effort"``, ``"mode"``, ``"profile"``,
    ``"provider"``); they are hidden. ``limit``: ``{role: glob patterns}``, the
    only model / effort / mode values offered, e.g. ``{"effort": ["low", "medium"]}``.
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
    suggestions: Suggestions = ()
    lock: Sequence[str] = ()
    limit: Mapping[str, Sequence[str]] = field(default_factory=dict)

    def __post_init__(self):
        _check_roles(self.lock, self.limit)

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


def _check_roles(lock: Sequence[str], limit: Mapping[str, Sequence[str]]) -> None:
    bad = [r for r in lock if r not in ROLES]
    if bad:
        raise ValueError(f"lock names unknown picker(s) {bad}; choose from {list(ROLES)}")
    bad = [r for r in limit if r not in ("model", "effort", "mode")]
    if bad:
        raise ValueError(f"limit names unknown picker(s) {bad}; choose from ['model', 'effort', 'mode']")
