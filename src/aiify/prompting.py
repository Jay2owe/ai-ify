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

from .profile import Launch, Profile, Turn, When, resolve
from .protocol import serialize

STATE_LIMIT = 6000


def command_for(app: str, python: str | None = None) -> str:
    """The shell command an agent runs to reach this app.

    Uses the app's own Python by full path: the agent's shell may not have
    ``aiify`` on PATH, and inside Codex's sandbox the Store ``python`` alias fails.
    The path uses forward slashes, which bash, PowerShell and cmd all accept;
    bash would drop the backslashes of a Windows path.
    """
    exe = (python or sys.executable).replace("\\", "/")
    return f'{subprocess.list2cmdline([exe])} -m aiify --app {app}'


def command_help(cmd: str, *, ui: bool = False, how: bool = True) -> str:
    lines = [
        f"Reach the app by running `{cmd} <op> ...` in a shell; each reply is one JSON line.",
        "Run these commands on their own, one per call or several joined with `;`. They then run "
        "without interrupting the person; wrapping them in other shell code (if, pipes, loops) "
        "makes the person approve each call.",
        f"  {cmd} describe                      what the app offers right now",
        f"  {cmd} state                         what is on screen and selected",
        f"  {cmd} action.list [match=plot.*]    backend actions (prefer these; no window needed)",
        f"  {cmd} action.describe NAME          one action's parameters",
        f"  {cmd} action.run NAME key=value ... run one; values are read as JSON, so write "
        "text values bare (id=abc123), quoting only a value with spaces",
    ]
    if how:
        lines.append(f'  {cmd} how "plain question"         where the app explains how to do something: '
                     "its actions, routes, screens, guide and map")
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
        "If the command cannot reach the app (for example \"no running app\"), tell the person and "
        "stop. Do not do the task another way, such as reading the app's files or using other "
        "tools: the person asked the app.",
    ]
    return "\n".join(lines)


def active_rules(rules: Iterable[When], turn: "Turn | dict") -> list[str]:
    """The context every matching rule adds for this message."""
    if isinstance(turn, dict):
        turn = Turn(state=turn)
    out = []
    for rule in rules:
        if rule.add_instructions and rule.matches(turn):
            text = rule.text_for(turn).strip()
            if text:
                out.append(text)
    return out


def state_text(state: dict | None) -> str:
    try:
        text = json.dumps(serialize(state or {}), ensure_ascii=False, separators=(",", ":"))
    except (TypeError, ValueError):
        text = str(state)
    return text if len(text) <= STATE_LIMIT else text[:STATE_LIMIT] + " ...(cut)"


def launch_text(launch: Launch, turn: Turn) -> str:
    """What the agent is told when a launch (a button in the app) starts the chat."""
    own = resolve(launch.instructions, turn, "launch instructions").strip()
    if not launch.label:
        return own
    return f"The person started this with \"{launch.label}\" in the app." + ("\n" + own if own else "")


def orientation(*, app: str, profile: Profile, state: dict, guide: str = "",
                command: str | None = None, ui: bool = False, instructions: str = "",
                launch: Launch | None = None, turn: Turn | None = None, how: bool = True) -> str:
    parts = [f"You are an assistant built into the app {app}. The person is talking to you "
             f"from inside the app; keep replies short and plain."]
    started = launch_text(launch, turn or Turn(state=state)) if launch is not None else ""
    for own in (instructions.strip(), profile.instructions_for(state).strip(), started):
        if own:
            parts.append(own)
    parts.append(command_help(command or command_for(app), ui=ui, how=how))
    if guide.strip():
        parts.append("About this app:\n" + guide.strip())
    return "\n\n".join(parts)


def build_message(text: str, *, app: str, profile: Profile, state: dict | None = None,
                  first: bool = False, rules: Sequence[When] = (), guide: str = "",
                  command: str | None = None, ui: bool = False, instructions: str = "",
                  turn: Turn | None = None, launch: Launch | None = None,
                  launch_new: bool = False, extra: Sequence[str] = (), how: bool = True) -> str:
    """The full text sent to the agent for one message from the person.
    ``instructions`` are the app's own (all profiles); the profile's follow them,
    then the launch's. Rules are matched against ``turn`` (what was typed, the
    settings, the launch), or the state alone when no turn is given.
    ``launch_new``: the launch has just started; its context goes with this message
    (in the orientation on a first message, else in its own block).
    ``extra``: more blocks (app notes, attachments) placed before the person's text.
    ``how``: whether the agent is told about the ``how`` search."""
    state = state or {}
    turn = turn or Turn(text=text, state=state, profile="", first=first)
    parts = []
    if first:
        parts.append(orientation(app=app, profile=profile, state=state, guide=guide,
                                 command=command, ui=ui, instructions=instructions,
                                 launch=launch if launch_new else None, turn=turn, how=how))
    elif launch is not None and launch_new:
        parts.append("[The person started a new request from the app]\n" + launch_text(launch, turn))
    parts.append("[App state now] " + state_text(state))
    if launch is not None and launch_new and turn.data is not None:
        parts.append("[Started with] " + state_text(turn.data))
    notes = active_rules(list(rules) + list(profile.rules) + list(launch.rules if launch else ()), turn)
    if notes:
        parts.append("[Applies now]\n" + "\n".join(f"- {n}" for n in notes))
    parts.extend(x for x in extra if x)
    parts.append("[Message from the person]\n" + text)
    return "\n\n".join(parts)
