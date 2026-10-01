"""What the agent is told: the app's instructions, how to reach the app, the
current state and any rule that applies, wrapped around the person's text.

The first message carries the orientation; later messages carry only the state,
the matching rules and the text, since the agent keeps the conversation.
"""
from __future__ import annotations

import json
import subprocess
import sys
from typing import Iterable, Sequence

from .profile import Profile, When
from .protocol import serialize

STATE_LIMIT = 6000


def command_for(app: str, python: str | None = None) -> str:
    """The shell command an agent runs to reach this app.

    Uses the app's own Python by full path: the agent's shell may not have
    ``aiify`` on PATH, and inside Codex's sandbox the Store ``python`` alias fails.
    """
    exe = python or sys.executable
    return f'{subprocess.list2cmdline([exe])} -m aiify --app {app}'


def command_help(cmd: str, *, ui: bool = False) -> str:
    lines = [
        f"Reach the app by running `{cmd} <op> ...` in a shell; each reply is one JSON line.",
        "Run these commands on their own, one per call or several joined with `;`. They then run "
        "without interrupting the person; wrapping them in other shell code (if, pipes, loops) "
        "makes the person approve each call.",
        f"  {cmd} describe                      what the app offers right now",
        f"  {cmd} state                         what is on screen and selected",
        f"  {cmd} action.list [match=plot.*]    backend actions (prefer these; no window needed)",
        f"  {cmd} action.describe NAME          one action's parameters",
        f"  {cmd} action.run NAME key=value ... run one; values are read as JSON",
    ]
    if ui:
        lines += [
            f"  {cmd} ui.do NAME key=value ...      a named on-screen command the app offers",
            f"  {cmd} ui tree                       the controls on screen, with refs like e12",
            f"  {cmd} ui click e12 | ui fill e7 0.4 act on one control (refs go stale after a change)",
            "Try a backend action first, then a named on-screen command, then the control tree.",
        ]
    lines += [
        'A reply with "code": "requires_confirmation" means the step needs the person\'s approval:',
        "describe what it will do, ask them, and only after they agree re-run it with --confirm.",
        'A reply with "code": "denied" means this agent is not allowed that step; do not work around it.',
    ]
    return "\n".join(lines)


def active_rules(rules: Iterable[When], state: dict) -> list[str]:
    return [r.add_instructions for r in rules if r.add_instructions and r.matches(state)]


def state_text(state: dict | None) -> str:
    try:
        text = json.dumps(serialize(state or {}), ensure_ascii=False, separators=(",", ":"))
    except (TypeError, ValueError):
        text = str(state)
    return text if len(text) <= STATE_LIMIT else text[:STATE_LIMIT] + " ...(cut)"


def orientation(*, app: str, profile: Profile, state: dict, guide: str = "",
                command: str | None = None, ui: bool = False, instructions: str = "") -> str:
    parts = [f"You are an assistant built into the app {app}. The person is talking to you "
             f"from inside the app; keep replies short and plain."]
    for own in (instructions.strip(), profile.instructions_for(state).strip()):
        if own:
            parts.append(own)
    parts.append(command_help(command or command_for(app), ui=ui))
    if guide.strip():
        parts.append("About this app:\n" + guide.strip())
    return "\n\n".join(parts)


def build_message(text: str, *, app: str, profile: Profile, state: dict | None = None,
                  first: bool = False, rules: Sequence[When] = (), guide: str = "",
                  command: str | None = None, ui: bool = False, instructions: str = "") -> str:
    """The full text sent to the agent for one message from the person.
    ``instructions`` are the app's own (all profiles); the profile's follow them."""
    state = state or {}
    parts = []
    if first:
        parts.append(orientation(app=app, profile=profile, state=state, guide=guide,
                                 command=command, ui=ui, instructions=instructions))
    parts.append("[App state now] " + state_text(state))
    notes = active_rules(list(rules) + list(profile.rules), state)
    if notes:
        parts.append("[Applies now]\n" + "\n".join(f"- {n}" for n in notes))
    parts.append("[Message from the person]\n" + text)
    return "\n\n".join(parts)
