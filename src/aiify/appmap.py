"""Build the app map: a developer step, run once per release.

    python -m aiify.appmap build myapp.main:app       # writes myapp/aiify_map.md
    python -m aiify.appmap check myapp.main:app       # exit 1 when the source changed since

The target is ``module:attribute``: the FastAPI app (with the agent mounted), the
ai-ify ``Agent``, or a function that builds the app (``myapp.main:create_app``). A hidden conversation on the developer's own Claude or Codex
subscription reads the app's source and writes a map of its screens and tasks in
plain language. Ship the file with the app (it sits in the package folder); the
embedded agent then finds it with no setting, and ``aiify how`` searches it.
Nothing is changed in the app; the agent may read files but every other tool is
refused.
"""
from __future__ import annotations

import argparse
import asyncio
import importlib
import json
import sys
import time
from pathlib import Path
from typing import Any

from .howto import MAP_NAME, read_header, source_files, source_hash

PROMPT = """You are writing the app map for the app "{app}": a guide that another AI assistant,
built into the app, will search to answer a person's questions like "how do I export the
summary?". The app's source is in the current folder. Read as much of it as you need
(pages, templates, scripts, route handlers, menus, dialogs). Change nothing.

Reply with only the map, in Markdown, exactly in this shape:

# App map: {app}

## Overview
What the app is for and who uses it, in 3 to 5 plain sentences.

## Screens
### <screen or view name>
What it shows, how to get to it, and its main controls by their visible labels.
(one ### section per screen, tab, dialog or view)

## Tasks
### How to <do something a person would ask for>
1. Numbered steps. For each step name the control by its visible label, or the action
   or route below that does it (exact name, e.g. route.include_all).
(one ### section per task; cover every task the app supports, 10 to 40 of them; phrase
titles the way a person would ask)

## Terms
### <term>
What the app means by it. (one ### per term a newcomer would not know)

Write for someone who has never seen the app. Use the visible labels on screen, not
internal function names, except where naming the action or route that does a step.
Do not invent features; leave out what you cannot find in the source.

What the running app already offers the assistant:

Actions and routes:
{actions}

Pages:
{pages}

The developer's guide:
{guide}

Source files (relative to the current folder):
{files}
"""


def load_target(target: str):
    """``module:attribute`` -> (FastAPI app or None, Agent or None, the module)."""
    module_name, _, attr = target.partition(":")
    if not module_name or not attr:
        raise SystemExit(f"target must be module:attribute, e.g. myapp.main:app (got {target!r})")
    sys.path.insert(0, str(Path.cwd()))
    module = importlib.import_module(module_name)
    obj = module
    for part in attr.split("."):
        obj = getattr(obj, part)
    app, agent = unpack_target(obj)
    return app, agent, module


def unpack_target(obj):
    """An app, an Agent, a factory of either, or a tuple holding them -> (app, agent)."""
    from .agent import Agent
    if callable(obj) and not isinstance(obj, Agent) and not hasattr(obj, "routes"):
        obj = obj()                                       # an app factory, e.g. create_app
    if isinstance(obj, tuple):
        obj = next((o for o in obj if isinstance(o, Agent) or hasattr(o, "routes")), obj[0])
    if isinstance(obj, Agent):
        return obj.web_app, obj
    agent = getattr(getattr(obj, "state", None), "aiify_agent", None)
    return obj, agent


def source_root(module, given: str | None) -> Path:
    if given:
        return Path(given).resolve()
    from .agent import package_dir
    root = package_dir(module.__name__, getattr(module, "__file__", None))
    if root is None:
        raise SystemExit("could not tell where the app's source is; pass --source DIR")
    return root.resolve()


def gather(app, agent, root: Path) -> dict:
    """What the map prompt is told: actions, routes, pages, guide and file list."""
    from .routes import RouteSource
    actions, pages, guide = [], [], ""
    routes = agent.route_source if agent is not None and agent.route_source is not None else (
        RouteSource(app) if app is not None else None)
    if agent is not None and agent.actions is not None:
        actions = [f"- {r['name']}: {r.get('summary', '')}" for r in agent.actions.summaries()]
    elif routes is not None:
        actions = [f"- {r['name']}: {r.get('summary', '')}" for r in routes.describe()["actions"]]
    if routes is not None:
        routes.specs()
        pages = [f"- {p['path']}: {p['summary']}" for p in routes.pages]
    if agent is not None:
        guide = agent.guide_text().strip()
    files = [p.relative_to(root).as_posix() for p in source_files(root)]
    return {"app": agent.app if agent is not None else root.name,
            "actions": "\n".join(actions[:300]) or "(none)",
            "pages": "\n".join(pages[:100]) or "(none)",
            "guide": guide[:12000] or "(none)",
            "files": "\n".join(files[:600]) + ("\n...(more)" if len(files) > 600 else "")}


async def write_map(material: dict, root: Path, *, provider: str, model: str | None, effort: str | None,
                    argv: list[str] | None = None, timeout: float = 1800.0, echo=print) -> str:
    from .engine import AcpSession

    chunks: list[str] = []

    def on_event(event: dict) -> None:
        kind = event.get("kind")
        if kind == "text":
            chunks.append(event.get("text") or "")
        elif kind == "tool":
            echo(f"  reading: {event.get('title', '')[:100]}")
        elif kind == "error":
            echo(f"  error: {event.get('text')}")

    async def refuse(request: dict) -> None:
        return None

    settings = {k: v for k, v in (("model", model), ("effort", effort)) if v}
    session = AcpSession(provider, cwd=root, on_event=on_event, permission_handler=refuse,
                         settings=settings, argv=argv)
    try:
        await asyncio.wait_for(session.start(), 300)
        summary = await asyncio.wait_for(session.send(PROMPT.format(**material)), timeout)
    finally:
        await session.close()
    stop = summary.get("stop")
    if stop == "auth_required":
        raise SystemExit(f"sign in to {provider} first (run `claude` or `codex` once and log in)")
    if stop != "end_turn":
        raise SystemExit(f"the agent stopped before finishing: {stop}")
    text = "".join(chunks).strip()
    start = text.find("# App map")
    if start < 0 or "## Tasks" not in text:
        raise SystemExit("the agent's reply was not a map:\n" + text[:2000])
    return text[start:]


def build(target: str, *, out: str | None = None, source: str | None = None, provider: str = "claude",
          model: str | None = None, effort: str | None = None, argv: list[str] | None = None,
          echo=print) -> Path:
    app, agent, module = load_target(target)
    root = source_root(module, source)
    path = Path(out).resolve() if out else root / MAP_NAME
    echo(f"Reading the source in {root} with {provider} ... (this can take several minutes)")
    material = gather(app, agent, root)
    t0 = time.monotonic()
    text = asyncio.run(write_map(material, root, provider=provider, model=model, effort=effort,
                                 argv=argv, echo=echo))
    header = (f"<!-- aiify app map: app={material['app']} sources={source_hash(root)} "
              f"built={time.strftime('%Y-%m-%d')} by={provider}{'/' + model if model else ''} -->")
    path.write_text(header + "\n" + text + "\n", encoding="utf-8")
    tasks = text.count("\n### How to")
    echo(f"Wrote {path} ({tasks} tasks) in {time.monotonic() - t0:.0f} s. Ship it with the app.")
    return path


def check(target: str, *, out: str | None = None, source: str | None = None, echo=print) -> int:
    app, agent, module = load_target(target)
    root = source_root(module, source)
    path = Path(out).resolve() if out else root / MAP_NAME
    if not path.is_file():
        echo(f"no app map at {path}; build one with: python -m aiify.appmap build {target}")
        return 1
    header = read_header(path.read_text(encoding="utf-8"))
    if header.get("sources") != source_hash(root):
        echo(f"{path} is out of date (built {header.get('built', '?')}); rebuild it with: "
             f"python -m aiify.appmap build {target}")
        return 1
    echo(f"{path} is current (built {header.get('built', '?')}).")
    return 0


def main(args: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m aiify.appmap", description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("build", "check"):
        p = sub.add_parser(name)
        p.add_argument("target", help="module:attribute of the FastAPI app or the ai-ify Agent")
        p.add_argument("--out", help=f"where the map goes (default: {MAP_NAME} in the app's package)")
        p.add_argument("--source", help="the app's source folder (default: its package folder)")
        if name == "build":
            p.add_argument("--provider", default="claude", choices=["claude", "codex"])
            p.add_argument("--model")
            p.add_argument("--effort")
            p.add_argument("--engine", help=argparse.SUPPRESS)       # JSON argv of a test agent
    a = ap.parse_args(args)
    if a.cmd == "check":
        return check(a.target, out=a.out, source=a.source)
    build(a.target, out=a.out, source=a.source, provider=a.provider, model=a.model, effort=a.effort,
          argv=json.loads(a.engine) if a.engine else None)
    return 0


if __name__ == "__main__":
    sys.exit(main())
