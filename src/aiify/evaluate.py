"""Measure how well the embedded agent does real tasks in an app, with and without
each discovery helper: the app's routes as actions, the ``how`` search, the app map,
and a prepared bundle of generated actions when the tasks file names one.

    python -m aiify.evaluate tasks.py --provider codex
    python -m aiify.evaluate tasks.py --mixes all,no-map --repeats 3 --only export-pdf

``tasks.py`` is written by the app's developer::

    from aiify.evaluate import Task, says, ran

    APP = "myapp.main:app"           # module:attribute, as for ``python -m aiify.appmap``,
                                     # or a function here that returns the app
    ENV = {"MYAPP_AI": "1"}          # set before the app is imported
    PAGE = "/"                       # the page opened in a hidden browser (None: no page)
    PREPARED = "aiify_prepared"      # optional: a verified bundle from python -m aiify.prepare,
                                     # relative to this file; compared like the other helpers
    def use_prepared(prepared, app): # optional: wire the bundle to the app once it is loaded
        prepared.module.bind(app)

    def prepare(out_dir):            # optional: once, before the app is imported
        ...                          # e.g. copy test data and point the app at it

    def seed(ctx):                   # optional: once, after the page is open
        ctx.data["sample_id"] = ...  # e.g. load demo data; tasks read ctx.data

    TASKS = [
        Task("export-pdf", "How do I export the summary as a PDF?", check=says("Publication")),
        Task("add-sample", "Add sample M04 with genotype APP.",
             check=lambda run: any(s["name"] == "M04" for s in run.state.get("samples", []))),
    ]

Every run is a new chat. Approvals are answered automatically (``--approve no``
refuses them instead) and counted. Each run is checked by the task's ``check``,
which gets a :class:`Run`: the reply, the app state afterwards, the commands the
agent ran and the approvals it needed. Results go to ``runs.jsonl`` (written as
they finish, so ``--resume`` carries on after an interruption) and ``report.md``.

A run uses the agent's provider on the developer's own subscription, so a round
costs real usage: ``--stop-at`` ends it when the provider's usage gets that high.
"""
from __future__ import annotations

import argparse
import asyncio
import concurrent.futures
import importlib.util
import json
import os
import re
import socket
import statistics
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Sequence

HELPERS = ("routes", "how", "app_map")
MIXES: dict[str, dict[str, bool]] = {
    "all": {"routes": True, "how": True, "app_map": True},
    "none": {"routes": False, "how": False, "app_map": False},
    "no-routes": {"routes": False, "how": True, "app_map": True},
    "no-how": {"routes": True, "how": False, "app_map": True},
    "no-map": {"routes": True, "how": True, "app_map": False},
}
LEAVE_ONE_OUT = {"routes": "no-routes", "how": "no-how", "app_map": "no-map"}


def mixes_for(prepared: bool = False) -> dict[str, dict[str, bool]]:
    """The helper mixes; with a prepared bundle (``PREPARED`` in the tasks file) it is
    one more helper: on in every mix but ``none`` and ``no-prepared``."""
    if not prepared:
        return dict(MIXES)
    out = {name: {**mix, "prepared": name != "none"} for name, mix in MIXES.items()}
    out["no-prepared"] = {"routes": True, "how": True, "app_map": True, "prepared": False}
    return out


class _JoinedGuide:
    """The app's own guide with a prepared bundle's guide added as one more topic."""

    TOPIC = "prepared actions"

    def __init__(self, base, extra: str):
        self.base, self.extra = base, extra

    def _base_text(self, *args) -> str:
        g = self.base
        if hasattr(g, "read") and callable(g.read):
            g = g.read(*args)
        elif callable(g):
            g = g()
        if isinstance(g, dict):
            g = g.get("content") or g.get("text") or ""
        return str(g or "")

    def topics(self) -> list[str]:
        base = getattr(self.base, "topics", None)
        return [*(base() if callable(base) and callable(getattr(self.base, "read", None)) else [""]), self.TOPIC]

    def read(self, topic=None) -> str:
        if topic == self.TOPIC:
            return self.extra
        if topic:
            return self._base_text(topic)
        return (self._base_text() + "\n\n## Prepared actions\n\n" + self.extra).strip()


def _prepared_switch(agent, path: str | Path, wire: Callable | None = None, app=None) -> Callable[[bool], None]:
    """Load a verified bundle once; the returned function adds its actions and guide to
    the agent, or takes them away again."""
    from .actions import ActionHost, combine
    from .prepare import load_prepared
    bundle = load_prepared(Path(path), app=None if wire is not None else app)   # bind(app) unless the tasks file wires it
    if wire is not None:
        wire(bundle)
    if agent.actions is None:                             # an app with no actions of its own
        agent.actions = ActionHost(None, agent.profile.policy(), ask_user=agent._ask_user)
        agent.actions.register(agent.port)
    host = agent.actions
    base_source = host.source
    base_guide = agent.guide
    joined = _JoinedGuide(base_guide, bundle.guide)

    def switch(on: bool) -> None:
        host.source = combine(base_source, bundle.actions) if on else base_source   # the app's own names win
        agent.guide = joined if on else base_guide
        agent._static_entries = None                      # the how search re-reads the guide
    return switch


# -- what a developer writes ----------------------------------------------------------
@dataclass
class Task:
    """One thing a person would ask the app's assistant to do or explain.

    ``check(run)`` returns ``True``/``False``, or ``(passed, note)``. ``setup(ctx)``
    runs before each chat (default: reload the page so it starts fresh)."""
    name: str
    prompt: str
    check: Callable[["Run"], Any]
    setup: Callable[["Context"], Any] | None = None
    timeout: float | None = None
    solve: Callable[["Context"], Any] | None = None   # what a correct agent would do: for --check-tasks


@dataclass
class Run:
    """What one chat produced, for a task's check."""
    task: str
    mix: str
    prompt: str
    reply: str
    state: dict
    commands: list[dict]
    approvals: list[dict]
    summary: dict
    seconds: float
    agent: Any = field(default=None, repr=False)
    data: dict = field(default_factory=dict)      # what the tasks file's ``seed`` set up
    page: Any = field(default=None, repr=False)   # the Playwright page afterwards, or None

    def says(self, *words: str) -> bool:
        low = self.reply.lower()
        return all(w.lower() in low for w in words)


def says(*words: str) -> Callable[[Run], tuple[bool, str]]:
    """Check: the reply mentions every word or phrase (case ignored)."""
    def check(run: Run):
        missing = [w for w in words if w.lower() not in run.reply.lower()]
        return (not missing, "missing: " + ", ".join(missing) if missing else "")
    return check


def says_any(*words: str) -> Callable[[Run], tuple[bool, str]]:
    """Check: the reply mentions at least one of the words or phrases."""
    def check(run: Run):
        hit = any(w.lower() in run.reply.lower() for w in words)
        return (hit, "" if hit else "none of: " + ", ".join(words))
    return check


def ran(pattern: str) -> Callable[[Run], tuple[bool, str]]:
    """Check: some command the agent ran matches this regular expression."""
    rx = re.compile(pattern, re.I)
    def check(run: Run):
        hit = any(rx.search(c.get("title", "")) for c in run.commands if c.get("status") != "failed")
        return (hit, "" if hit else f"no command matched {pattern!r}")
    return check


def all_of(*checks: Callable[[Run], Any]) -> Callable[[Run], tuple[bool, str]]:
    """Check: every one of these checks passes."""
    def check(run: Run):
        notes = []
        for c in checks:
            ok, note = _verdict(c(run))
            if not ok:
                notes.append(note or "failed")
        return (not notes, "; ".join(notes))
    return check


@dataclass
class Context:
    """What a task's ``setup`` can use."""
    agent: Any
    url: str
    page: Any = None                  # a Playwright page, or None with --no-page
    data: dict = field(default_factory=dict)      # what ``seed`` set up, for setups and checks

    def run(self, coro, timeout: float = 120):
        """Run a coroutine on the agent's event loop and return its result; on timeout
        the coroutine is cancelled rather than left running."""
        fut = asyncio.run_coroutine_threadsafe(coro, self.agent.loop)
        try:
            return fut.result(timeout)
        except concurrent.futures.TimeoutError:
            fut.cancel()
            raise

    def reload(self) -> None:
        """Reload the page and wait until the panel is connected again."""
        if self.page is None:
            return
        self.page.reload(wait_until="networkidle")
        _wait_attached(self)


# -- running ----------------------------------------------------------------------------
def _verdict(result: Any) -> tuple[bool, str]:
    if isinstance(result, tuple):
        return bool(result[0]), str(result[1] if len(result) > 1 else "")
    return bool(result), ""


def _settle(ctx: Context, timeout: float = 120) -> None:
    """Make sure no earlier answer is still running before the next chat starts: stop it
    and wait. A chat started too early is refused by the agent and not counted."""
    if not ctx.agent.busy:
        return
    try:
        ctx.run(ctx.agent.cancel(), timeout=30)
    except Exception:                                     # noqa: BLE001 - waited for below
        pass
    end = time.monotonic() + timeout
    while ctx.agent.busy and time.monotonic() < end:
        time.sleep(0.5)


def _wait_attached(ctx: Context, timeout: float = 60) -> None:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if ctx.agent.relay.attached:
            return
        time.sleep(0.1)
    raise RuntimeError("the page did not connect to the assistant")


def _choose(options: Sequence[dict], approve: bool) -> str | None:
    kinds = ("allow_once", "allow_always") if approve else ("reject_once", "reject_always")
    for kind in kinds:
        for o in options or ():
            if o.get("kind") == kind:
                return o.get("id")
    return None


async def _chat(agent, prompt: str, *, timeout: float, approve: bool) -> dict:
    """Send one message in a new chat, answer approvals, and collect what happened."""
    q = agent.subscribe()
    events: list[dict] = []
    approvals: list[dict] = []
    timed_out = False
    t0 = time.monotonic()
    task = asyncio.ensure_future(agent.send(prompt))
    try:
        while not (task.done() and q.empty()):
            try:
                ev = await asyncio.wait_for(q.get(), 0.5)
            except asyncio.TimeoutError:
                if not timed_out and time.monotonic() - t0 > timeout:
                    timed_out = True
                    await agent.cancel()
                continue
            events.append(ev)
            if ev.get("kind") == "permission":
                option = _choose(ev.get("options") or [], approve)
                approvals.append({"title": str(ev.get("title", ""))[:300], "answer": option})
                agent.answer(ev.get("id"), option)
        try:
            summary = task.result()
        except Exception as exc:                          # noqa: BLE001 - recorded as the run's error
            summary = {"stop": f"error: {type(exc).__name__}: {exc}"}
    finally:
        agent.unsubscribe(q)
    await agent.refresh_page_state()
    tools: dict[str, dict] = {}
    for ev in events:
        if ev.get("kind") == "tool":
            tools[ev.get("id")] = {"title": str(ev.get("title", ""))[:300], "status": ev.get("status") or ""}
        elif ev.get("kind") == "tool_update" and ev.get("id") in tools:
            if ev.get("status"):
                tools[ev["id"]]["status"] = ev["status"]
            if ev.get("title"):
                tools[ev["id"]]["title"] = str(ev["title"])[:300]
    return {"reply": "".join(ev.get("text", "") for ev in events if ev.get("kind") == "text"),
            "commands": list(tools.values()), "approvals": approvals,
            "summary": {**summary, "timed_out": timed_out}, "seconds": round(time.monotonic() - t0, 1),
            "state": agent.current_state()}


def _prepare_chat(agent, mix: dict[str, bool], *, provider, profile, roles, prepared=None) -> dict:
    async def go():
        if profile and profile != agent.profile_name:
            await agent.configure(profile=profile)
        if provider and provider != agent.provider:
            await agent.configure(provider=provider)
        if prepared is not None:
            prepared(mix["prepared"])
        helpers = agent.set_helpers(**{k: v for k, v in mix.items() if k in HELPERS})
        if prepared is not None:
            helpers["prepared"] = mix["prepared"]
        await agent.new_chat()
        if roles:
            await agent.configure(**roles)
        return helpers
    return go()


def _usage_high(agent, provider: str, stop_at: float) -> tuple[str, float | None] | None:
    """(why, seconds to wait) when usage is at ``stop_at``: a 5-hour window is waited out
    (seconds until it resets), any longer window ends the round (``None``)."""
    snap = agent.usage.snapshot() or {}
    rows = [r for r in (snap.get("providers") or {}).get(provider, []) or []
            if r.get("used") is not None and not r.get("expired") and float(r["used"]) >= stop_at]
    if not rows:
        return None
    why = "; ".join(f"{provider} {r.get('label', '')} usage at {r['used']:.0f}%" for r in rows)
    if all(r.get("kind") == "five_hour" and r.get("resets_in_s") is not None for r in rows):
        return why, float(max(r["resets_in_s"] for r in rows))
    return why, None


def _refresh_claude_usage(ctx: "Context", provider: str) -> None:
    """Claude reports its limits only through ``/usage``: read them now (no tokens used),
    unless the app turned those checks off."""
    if provider != "claude" or ctx.agent.limit_check_every is None:
        return
    try:
        ctx.run(ctx.agent._claude_limits(), timeout=180)
    except Exception:                                     # noqa: BLE001 - limits are best effort
        pass


def _unanswered(row: dict) -> bool:
    """The provider never answered (a usage limit or its own error): not the agent's
    result, so it is left out of the pass rates and run again by ``--resume``."""
    return bool(row.get("unanswered") or str(row.get("stop") or "").startswith("error"))


def _latest(rows: list[dict]) -> list[dict]:
    """One row per task, mix and repeat: a resumed re-run replaces the earlier row."""
    keyed = {}
    for r in rows:
        keyed[(r["task"], r["mix"], r["repeat"])] = r
    return list(keyed.values())


def load_tasks(path: str | Path):
    path = Path(path).resolve()
    spec = importlib.util.spec_from_file_location(f"aiify_eval_tasks_{abs(hash(str(path)))}", path)
    if spec is None or spec.loader is None:
        raise SystemExit(f"cannot load tasks from {path}")
    module = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(path.parent))
    spec.loader.exec_module(module)
    for name in ("APP", "TASKS"):
        if not hasattr(module, name):
            raise SystemExit(f"{path.name} needs {name} (see python -m aiify.evaluate --help)")
    names = [t.name for t in module.TASKS]
    if len(set(names)) != len(names):
        raise SystemExit("task names must be unique")
    return module


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class _Server:
    """The app on a free local port, in a background thread (uvicorn)."""

    def __init__(self, app):
        import uvicorn
        self.port = _free_port()
        self.server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=self.port,
                                                    log_level="warning", lifespan="on"))
        self.thread = threading.Thread(target=self.server.run, name="aiify-evaluate-server", daemon=True)

    def __enter__(self):
        self.thread.start()
        end = time.monotonic() + 120
        while not self.server.started:
            if not self.thread.is_alive() or time.monotonic() > end:
                raise RuntimeError("the app did not start")
            time.sleep(0.1)
        return self

    def __exit__(self, *exc):
        self.server.should_exit = True
        self.thread.join(30)


class _Browser:
    """A hidden browser page on the app, so on-screen commands work during the runs."""

    def __init__(self, url: str):
        self.url = url
        self.pw = self.browser = self.page = None

    def __enter__(self):
        from playwright.sync_api import sync_playwright
        self.pw = sync_playwright().start()
        try:
            self.browser = self.pw.chromium.launch(channel="msedge", headless=True)
        except Exception:                                 # noqa: BLE001 - no Edge: Playwright's own
            self.browser = self.pw.chromium.launch(headless=True)
        self.page = self.browser.new_page(viewport={"width": 1440, "height": 1000})
        self.page.goto(self.url, wait_until="networkidle")
        return self

    def __exit__(self, *exc):
        for closer in (getattr(self.browser, "close", None), getattr(self.pw, "stop", None)):
            try:
                if closer:
                    closer()
            except Exception:                             # noqa: BLE001 - closing anyway
                pass


def evaluate(tasks_path: str | Path, *, out: str | Path | None = None, mixes: Sequence[str] | None = None,
             repeats: int = 1, only: Sequence[str] = (), provider: str | None = None,
             profile: str | None = None, model: str | None = None, effort: str | None = None,
             mode: str | None = None, timeout: float = 600, approve: bool = True,
             stop_at: float = 95, page: bool = True, resume: bool = False, check_tasks: bool = False,
             echo=print) -> Path:
    """Run every task under every helper mix; returns the folder with the results."""
    module = load_tasks(tasks_path)
    prepared_path = getattr(module, "PREPARED", None)
    known = mixes_for(bool(prepared_path))
    mixes = list(mixes or known)
    unknown = [m for m in mixes if m not in known]
    if unknown:
        raise SystemExit(f"unknown mix(es) {', '.join(unknown)}; choose from {', '.join(known)}")
    tasks = [t for t in module.TASKS if not only or t.name in only]
    if not tasks:
        raise SystemExit("no tasks to run")
    for key, value in (getattr(module, "ENV", None) or {}).items():
        os.environ[key] = str(value)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    out_dir = Path(out) if out else None
    if out_dir is not None:
        out_dir.mkdir(parents=True, exist_ok=True)
    if callable(getattr(module, "prepare", None)):
        module.prepare(out_dir)

    from .appmap import load_target, unpack_target
    app, agent = (load_target(module.APP)[:2] if isinstance(module.APP, str) else unpack_target(module.APP))
    if agent is None:
        raise SystemExit(f"{module.APP} has no ai-ify agent mounted")
    wire = getattr(module, "use_prepared", None)
    prepared = _prepared_switch(agent, Path(module.__file__).parent / prepared_path,
                                (lambda bundle: wire(bundle, app)) if callable(wire) else None,
                                app=app) if prepared_path else None
    if out_dir is None:
        out_dir = agent.work_folder() / "evaluations" / stamp
        out_dir.mkdir(parents=True, exist_ok=True)
    runs_file = out_dir / "runs.jsonl"
    done = set()
    if resume and runs_file.is_file():
        for line in runs_file.read_text(encoding="utf-8").splitlines():
            if line.strip():
                r = json.loads(line)
                key = (r["task"], r["mix"], r["repeat"])
                if _unanswered(r):
                    done.discard(key)
                else:
                    done.add(key)
    roles = {k: v for k, v in (("model", model), ("effort", effort), ("mode", mode)) if v}
    plan = [(rep, t, m) for rep in range(1, repeats + 1) for t in tasks for m in mixes
            if (t.name, m, rep) not in done]
    if check_tasks:
        echo(f"Checking {len(tasks)} tasks without an agent -> {out_dir}")
    else:
        echo(f"{len(plan)} chats ({len(tasks)} tasks x {len(mixes)} mixes x {repeats} repeats"
             f"{', resuming' if done else ''}) -> {out_dir}")
    page_path = getattr(module, "PAGE", "/") if page else None
    stopped = None
    unanswered_in_a_row = 0
    with _Server(app) as server:
        url = f"http://127.0.0.1:{server.port}"
        end = time.monotonic() + 60
        while agent.loop is None and time.monotonic() < end:
            time.sleep(0.1)
        browser = _Browser(url + page_path) if page_path is not None else None
        with (browser or _Nothing()):
            ctx = Context(agent=agent, url=url, page=browser.page if browser else None)
            if browser:
                _wait_attached(ctx)
            if callable(getattr(module, "seed", None)):
                module.seed(ctx)
            if check_tasks:
                _check_tasks(ctx, tasks, out_dir, echo)
                return out_dir
            used_provider = provider or agent.provider
            for i, (rep, task, mix) in enumerate(plan, 1):
                if i % 5 == 1:
                    _refresh_claude_usage(ctx, used_provider)
                high = _usage_high(agent, used_provider, stop_at)
                while high and high[1] is not None:            # a short window: wait for it to reset
                    echo(f"waiting {high[1] / 60:.0f} min before run {i}: {high[0]} (--stop-at {stop_at:g})")
                    time.sleep(high[1] + 60)
                    _refresh_claude_usage(ctx, used_provider)
                    high = _usage_high(agent, used_provider, stop_at)
                if high:
                    stopped = f"stopped before run {i}: {high[0]} (--stop-at {stop_at:g})"
                    echo(stopped)
                    break
                helpers = ctx.run(_prepare_chat(agent, known[mix], provider=provider, profile=profile,
                                                roles=roles, prepared=prepared))
                limit = task.timeout or timeout
                try:
                    _settle(ctx)
                    (task.setup or Context.reload)(ctx)
                    got = ctx.run(_chat(agent, task.prompt, timeout=limit, approve=approve), timeout=limit + 120)
                    run = Run(task=task.name, mix=mix, prompt=task.prompt, agent=agent, data=ctx.data, page=ctx.page, **got)
                    passed, note = _verdict(task.check(run))
                except concurrent.futures.TimeoutError:        # it did not stop even when asked to
                    got = {"reply": "", "commands": [], "approvals": [], "summary": {"timed_out": True},
                           "seconds": limit + 120, "state": {}}
                    passed, note = False, "it kept going after being asked to stop"
                    _settle(ctx)
                except Exception as exc:                  # noqa: BLE001 - a failed run, not a failed round
                    got = {"reply": "", "commands": [], "approvals": [], "summary": {}, "seconds": 0, "state": {}}
                    passed, note = False, f"{type(exc).__name__}: {exc}"
                stop = (got["summary"] or {}).get("stop")
                unanswered = isinstance(stop, str) and stop.startswith("error")
                if unanswered:
                    passed, note = False, stop                 # the agent never answered
                if (got["summary"] or {}).get("timed_out"):
                    passed, note = False, (note + "; " if note else "") + f"no answer within {task.timeout or timeout:g} s"
                record = {"task": task.name, "mix": mix, "repeat": rep, "passed": passed, "note": note,
                          "unanswered": unanswered,
                          "helpers": helpers, "provider": used_provider, "settings": dict(agent.settings),
                          "seconds": got["seconds"], "stop": stop,
                          "first_words": (got["summary"] or {}).get("first_words"),
                          "commands": got["commands"], "failed_commands": sum(c["status"] == "failed" for c in got["commands"]),
                          "how_calls": sum(bool(re.search(r"\bhow\b\s", c["title"])) and "aiify" in c["title"]
                                           for c in got["commands"]),
                          "approvals": got["approvals"], "reply": got["reply"][:4000],
                          "state": json.loads(json.dumps(got["state"], default=str))}
                with runs_file.open("a", encoding="utf-8") as f:
                    f.write(json.dumps(record, ensure_ascii=False) + "\n")
                echo(f"[{i}/{len(plan)}] {mix:<9} {task.name} #{rep}: {'pass' if passed else 'FAIL'} "
                     f"({got['seconds']:.0f} s, {len(got['commands'])} commands)" + (f" - {note}" if note and not passed else ""))
                unanswered_in_a_row = unanswered_in_a_row + 1 if unanswered else 0
                if unanswered_in_a_row >= 2:                   # a usage limit: every later chat fails the same way
                    stopped = (f"stopped after run {i}: {used_provider} gave no answer twice in a row "
                               f"({(got['reply'] or note).strip()[:200]}); --resume runs them again")
                    echo(stopped)
                    break
    report = write_report(out_dir, app=agent.app, mixes=mixes, tasks=[t.name for t in tasks], stopped=stopped)
    echo(f"Report: {report}")
    return out_dir


def _offline_run(ctx: Context, task: Task, reply: str) -> Run:
    ctx.run(ctx.agent.refresh_page_state())
    return Run(task=task.name, mix="check", prompt=task.prompt, reply=reply, state=ctx.agent.current_state(),
               commands=[], approvals=[], summary={}, seconds=0.0, agent=ctx.agent, data=ctx.data, page=ctx.page)


def _check_tasks(ctx: Context, tasks: Sequence[Task], out_dir: Path, echo) -> bool:
    """No agent: each check must fail on the fresh setup and pass once ``solve`` has done
    what a correct agent would (its return value is the reply). Writes task-check.json."""
    rows = []
    for task in tasks:
        row = {"task": task.name}
        try:
            (task.setup or Context.reload)(ctx)
            row["before"] = _verdict(task.check(_offline_run(ctx, task, "")))
            if task.solve is None:
                row["problem"] = "no solve(ctx) to show what passes"
            else:
                row["after"] = _verdict(task.check(_offline_run(ctx, task, str(task.solve(ctx) or ""))))
                if row["before"][0]:
                    row["problem"] = "passes before the agent does anything"
                elif not row["after"][0]:
                    row["problem"] = f"fails after solve: {row['after'][1] or 'check failed'}"
        except Exception as exc:                          # noqa: BLE001 - reported per task
            row["problem"] = f"{type(exc).__name__}: {exc}"
        rows.append(row)
        echo(f"{task.name}: {'ok' if 'problem' not in row else row['problem']}")
    ok = all("problem" not in r for r in rows)
    (out_dir / "task-check.json").write_text(json.dumps({"ok": ok, "tasks": rows}, indent=1, default=str),
                                             encoding="utf-8")
    echo("Every check fails before and passes after." if ok else "Some checks need fixing; see task-check.json.")
    return ok


class _Nothing:
    def __enter__(self):
        return None

    def __exit__(self, *exc):
        return False


# -- the report -------------------------------------------------------------------------
def _rate(rows: list[dict]) -> str:
    return f"{sum(r['passed'] for r in rows)}/{len(rows)}" if rows else "-"


def _pct(rows: list[dict]) -> float | None:
    return 100.0 * sum(r["passed"] for r in rows) / len(rows) if rows else None


def _mean(values: list[float]) -> str:
    values = [v for v in values if v is not None]
    return f"{statistics.mean(values):.1f}" if values else "-"


def write_report(out_dir: Path, *, app: str = "", mixes: Sequence[str] = (), tasks: Sequence[str] = (),
                 stopped: str | None = None) -> Path:
    """``report.md`` and ``summary.json`` from ``runs.jsonl`` (also after a resume)."""
    rows = [json.loads(line) for line in (out_dir / "runs.jsonl").read_text(encoding="utf-8").splitlines()
            if line.strip()] if (out_dir / "runs.jsonl").is_file() else []
    rows = _latest(rows)
    unanswered = [r for r in rows if _unanswered(r)]
    rows = [r for r in rows if not _unanswered(r)]
    seen = list(dict.fromkeys([*MIXES, "no-prepared", *(r["mix"] for r in rows)]))
    mixes = [m for m in (mixes or seen) if any(r["mix"] == m for r in rows)]
    tasks = list(tasks) or sorted({r["task"] for r in rows})
    by_mix = {m: [r for r in rows if r["mix"] == m] for m in mixes}
    first = rows[0] if rows else {}
    lines = [f"# Agent evaluation{': ' + app if app else ''}", "",
             f"{len(rows)} chats · provider {first.get('provider', '?')} · settings "
             f"{json.dumps(first.get('settings', {}))} · {time.strftime('%Y-%m-%d')}", ""]
    if stopped:
        lines += [f"**Incomplete:** {stopped}", ""]
    if unanswered:
        lines += [f"**Not counted:** {len(unanswered)} chat(s) got no answer from the provider "
                  "(a usage limit or its own error); `--resume` runs them again.", ""]
        lines += [f"- {r['task']} · {r['mix']} · #{r['repeat']}: {r['note'] or r['stop']}" for r in unanswered]
        lines.append("")
    lines += ["## Pass rate by helper mix", "",
              "| Mix | Helpers on | Passed | Mean time (s) | Mean commands | Failed commands | Approvals |",
              "|---|---|---|---|---|---|---|"]
    for m in mixes:
        rs = by_mix[m]
        on = ", ".join(h for h, v in (rs[0]["helpers"] if rs else {}).items() if v) or "none"
        lines.append(f"| {m} | {on} | {_rate(rs)} | {_mean([r['seconds'] for r in rs])} | "
                     f"{_mean([len(r['commands']) for r in rs])} | {_mean([r['failed_commands'] for r in rs])} | "
                     f"{_mean([len(r['approvals']) for r in rs])} |")
    adds = []
    for helper, without in {**LEAVE_ONE_OUT, "prepared": "no-prepared"}.items():
        if "all" in by_mix and without in by_mix:
            a, b = _pct(by_mix["all"]), _pct(by_mix[without])
            if a is not None and b is not None:
                adds.append(f"| {helper} | {a:.0f}% | {b:.0f}% | {a - b:+.0f} points |")
    if adds:
        lines += ["", "## What each helper adds", "",
                  "Pass rate with every helper, and with all but this one.", "",
                  "| Helper | All on | Without it | Difference |", "|---|---|---|---|", *adds]
    lines += ["", "## Each task", "", "| Task | " + " | ".join(mixes) + " |",
              "|---|" + "---|" * len(mixes)]
    for t in tasks:
        lines.append(f"| {t} | " + " | ".join(_rate([r for r in by_mix[m] if r["task"] == t]) for m in mixes) + " |")
    fails = [r for r in rows if not r["passed"]]
    if fails:
        lines += ["", "## Failures", ""]
        for r in fails:
            lines.append(f"- **{r['task']}** · {r['mix']} · #{r['repeat']}: {r['note'] or 'check failed'}")
    (out_dir / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    summary = {m: {"passed": sum(r["passed"] for r in by_mix[m]), "runs": len(by_mix[m])} for m in mixes}
    (out_dir / "summary.json").write_text(json.dumps({"app": app, "mixes": summary, "stopped": stopped,
                                                      "unanswered": len(unanswered)},
                                                     indent=2), encoding="utf-8")
    return out_dir / "report.md"


def main(args: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m aiify.evaluate", description=__doc__.splitlines()[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter,
                                 epilog="\n".join(__doc__.splitlines()[1:]))
    ap.add_argument("tasks", help="the tasks file (APP, TASKS, optional ENV, PAGE, prepare)")
    ap.add_argument("--out", help="results folder (default: the app's work folder/evaluations/<time>)")
    ap.add_argument("--mixes", default="", help=f"comma-separated, from: {', '.join(mixes_for(True))} "
                                                 "(default: all of them; no-prepared needs PREPARED)")
    ap.add_argument("--repeats", type=int, default=1)
    ap.add_argument("--only", default="", help="comma-separated task names")
    ap.add_argument("--provider", choices=["claude", "codex"])
    ap.add_argument("--profile")
    ap.add_argument("--model")
    ap.add_argument("--effort")
    ap.add_argument("--mode")
    ap.add_argument("--timeout", type=float, default=600, help="seconds per chat")
    ap.add_argument("--approve", choices=["yes", "no"], default="yes", help="how approvals are answered")
    ap.add_argument("--stop-at", type=float, default=95, help="stop when provider usage reaches this %%")
    ap.add_argument("--no-page", action="store_true", help="no hidden browser page (backend only)")
    ap.add_argument("--resume", action="store_true", help="skip runs already in --out's runs.jsonl")
    ap.add_argument("--check-tasks", action="store_true",
                    help="no agent: check that each task's check fails at setup and passes after its solve")
    a = ap.parse_args(args)
    if a.resume and not a.out:
        ap.error("--resume needs --out")
    folder = evaluate(a.tasks, out=a.out, mixes=[m.strip() for m in a.mixes.split(",") if m.strip()] or None,
                      repeats=a.repeats, only=[t.strip() for t in a.only.split(",") if t.strip()],
                      provider=a.provider, profile=a.profile, model=a.model, effort=a.effort, mode=a.mode,
                      timeout=a.timeout, approve=a.approve == "yes", stop_at=a.stop_at, page=not a.no_page,
                      resume=a.resume, check_tasks=a.check_tasks)
    if a.check_tasks:
        return 0 if json.loads((folder / "task-check.json").read_text(encoding="utf-8"))["ok"] else 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
