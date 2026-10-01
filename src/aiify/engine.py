"""The agent engine: one live ACP (Agent Client Protocol) session per chat.

The adapters run under the Claude / Codex logins already on the machine -
no API keys.

    python -m aiify.engine --provider claude "Reply with three words"
"""
from __future__ import annotations

import asyncio
import atexit
import os
import shutil
import subprocess
import sys
import time
import uuid
import weakref
from pathlib import Path
from typing import Any, Awaitable, Callable

import acp
from acp import schema, text_block

from . import __version__
from .protocol import home, serialize

# One table, so a future adapter rename is a one-line change
# (the adapters were renamed once already: @zed-industries/* -> @agentclientprotocol/*).
#
# "cli" runs the vendor CLI the adapter bundles, so no separate install is needed.
# "signin" lists the adapter's sign-in methods that use the subscription (not API
# keys); "signin_check" (appended to the adapter command) exits 0 once signed in.
PROVIDERS = {
    "claude": {"argv": ["npx", "-y", "@agentclientprotocol/claude-agent-acp"],
               "keys": {"model": "model", "effort": "effort", "mode": "mode"},
               "label": "Claude",
               "cli": ["npx", "-y", "@agentclientprotocol/claude-agent-acp", "--cli"],
               "signin": ["claude-ai-login"],
               "signin_check": ["--cli", "auth", "status"]},
    "codex": {"argv": ["npx", "-y", "@agentclientprotocol/codex-acp"],
              "keys": {"model": "model", "effort": "reasoning_effort", "mode": "mode"},
              "label": "Codex",
              "cli": ["npx", "-y", "-p", "@agentclientprotocol/codex-acp", "codex"],
              "signin": ["chat-gpt"]},
}
# Gemini is excluded: over ACP it answers "This client is no longer supported for
# Gemini Code Assist for individuals" on this account.

AUTH_REQUIRED = -32000                 # ACP's "sign in first" error code
NO_NODE = ("Node.js is not installed, and the agent needs it. Install it from "
           "https://nodejs.org, then reopen the app.")

STRIP_ENV_EXACT = {"CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT", "CLAUDE_CODE_SESSION"}
STRIP_ENV_PREFIXES = ("AC_",)
LINE_LIMIT = 16 * 1024 * 1024

Event = dict
PermissionHandler = Callable[[dict], Awaitable["str | None"]]

_LIVE: "weakref.WeakSet[AcpSession]" = weakref.WeakSet()


ENGINE_ENV = "AIIFY_ENGINE_COMMAND"


def engine_override() -> list[str] | None:
    """For app tests: ``AIIFY_ENGINE_COMMAND`` (a JSON list) replaces every
    provider's adapter, e.g. ``["python", "-m", "aiify.testing.fake_agent"]``."""
    raw = os.environ.get(ENGINE_ENV)
    if not raw:
        return None
    import json
    try:
        argv = json.loads(raw)
    except ValueError:
        raise ValueError(f"{ENGINE_ENV} must be a JSON list of strings") from None
    if not (isinstance(argv, list) and argv and all(isinstance(a, str) for a in argv)):
        raise ValueError(f"{ENGINE_ENV} must be a JSON list of strings")
    return argv


def child_env(extra: dict | None = None) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items()
           if k not in STRIP_ENV_EXACT and not k.startswith(STRIP_ENV_PREFIXES)}
    env.update(extra or {})
    return env


def work_dir(app: str) -> Path:
    path = home() / "work" / "".join(c if c.isalnum() or c in "-_." else "_" for c in app)
    path.mkdir(parents=True, exist_ok=True)
    return path


def kill_tree(pid: int | None) -> None:
    if not pid:
        return
    try:
        if sys.platform == "win32":
            subprocess.run(["taskkill", "/T", "/F", "/PID", str(int(pid))], capture_output=True,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), timeout=15)
        else:
            import signal
            os.kill(int(pid), signal.SIGTERM)
    except Exception:
        pass


@atexit.register
def _kill_leftovers() -> None:
    for session in list(_LIVE):
        kill_tree(session.pid)


def needs_signin(exc: BaseException) -> bool:
    return isinstance(exc, acp.RequestError) and exc.code == AUTH_REQUIRED


async def signin_check(argv: list[str], env: dict | None = None, timeout: float = 60) -> bool | None:
    """Run a provider's sign-in check: True signed in, False not, None unknown."""
    exe = shutil.which(argv[0]) or argv[0]
    try:
        proc = await asyncio.create_subprocess_exec(
            exe, *argv[1:], env=child_env(env), stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return await asyncio.wait_for(proc.wait(), timeout) == 0
    except (OSError, asyncio.TimeoutError):
        return None


def _method(m) -> dict:
    d = _dump(m) or {}
    return {"id": d.get("id", ""), "name": d.get("name") or d.get("id", ""),
            "description": (d.get("description") or "").strip(), "type": d.get("type") or "agent",
            "args": list(d.get("args") or [])}


def _dump(obj):
    if hasattr(obj, "model_dump"):
        return obj.model_dump(mode="json", exclude_none=True, by_alias=True)
    return obj


def tool_detail(tc) -> str:
    """Readable command/output text from an ACP tool call or update."""
    parts = []
    raw = getattr(tc, "raw_input", None)
    if raw:
        parts.append(raw.get("command") if isinstance(raw, dict) and raw.get("command")
                     else _short(raw, 400))
    for c in getattr(tc, "content", None) or []:
        inner = getattr(c, "content", None)
        if inner is not None and getattr(inner, "text", None):
            parts.append(inner.text[:1500])
        elif getattr(c, "path", None):
            parts.append(f"edit {c.path}")
    out = getattr(tc, "raw_output", None)
    if out:
        if isinstance(out, dict):
            out = out.get("formatted_output") or out.get("aggregated_output") or out.get("stdout") or out
        parts.append(out[:1500] if isinstance(out, str) else _short(out, 1500))
    return "\n".join(str(p) for p in parts if p)


def command_text(tc) -> str:
    """The shell command a tool call wants to run, or "" (Codex sends a list)."""
    raw = getattr(tc, "raw_input", None)
    cmd = raw.get("command") if isinstance(raw, dict) else None
    if isinstance(cmd, list):
        cmd = subprocess.list2cmdline([str(c) for c in cmd])
    return cmd if isinstance(cmd, str) else ""


def _short(obj, n: int) -> str:
    import json
    try:
        return json.dumps(serialize(obj))[:n]
    except (TypeError, ValueError):
        return str(obj)[:n]


class AcpSession:
    """A live conversation with one ACP agent process.

    ``on_event(event)`` receives chat events (docs/protocol.md "Chat events").
    ``permission_handler(request)`` answers the agent's permission requests with
    an option id, or ``None`` to refuse; without one, requests are refused.
    ``auto_answer(request)`` may answer first without asking anyone (an option id),
    e.g. to let the agent run the app's own ``aiify`` command without a prompt.
    """

    def __init__(self, provider: str, *, cwd: Path | str,
                 on_event: Callable[[Event], None] | None = None,
                 permission_handler: PermissionHandler | None = None,
                 session_id: str | None = None,
                 settings: dict | None = None,
                 argv: list[str] | None = None,
                 env: dict | None = None,
                 auto_answer: Callable[[dict], "str | None"] | None = None):
        if provider not in PROVIDERS and argv is None and not engine_override():
            raise ValueError(f"unknown provider {provider!r}; choose from {', '.join(PROVIDERS)}")
        self.provider = provider
        self.cwd = str(cwd)
        self.on_event = on_event or (lambda e: None)
        self.permission_handler = permission_handler
        self.auto_answer = auto_answer
        self.resume_id = session_id
        self.settings = dict(settings or {})
        self.argv = list(argv or engine_override() or PROVIDERS[provider]["argv"])
        self.env = env
        self.keys = PROVIDERS.get(provider, PROVIDERS["claude"])["keys"]
        self.session_id: str | None = None
        self.capabilities: dict = {}
        self.auth_methods: list[dict] = []
        self.signed_out = False
        self.config: dict[str, dict] = {}
        self.pid: int | None = None
        self.busy = False
        self.startup_s: float | None = None
        self._conn = None
        self._task: asyncio.Task | None = None
        self._ready = asyncio.Event()
        self._stop = asyncio.Event()
        self._error: BaseException | None = None
        self._pending: dict[str, asyncio.Future] = {}
        self._turn: dict = {}
        self._quiet = False

    # -- events -----------------------------------------------------------------
    def emit(self, **event) -> None:
        try:
            self.on_event(event)
        except Exception:
            pass

    # -- the client side of ACP (the agent calls these) ------------------------------
    def on_connect(self, conn) -> None:
        pass

    async def session_update(self, session_id, update, **kw) -> None:
        if self._quiet:
            return
        kind = getattr(update, "session_update", "")
        if kind == "agent_message_chunk":
            if "first" not in self._turn and "t0" in self._turn:
                self._turn["first"] = time.monotonic() - self._turn["t0"]
            self.emit(kind="text", text=getattr(update.content, "text", ""))
        elif kind == "agent_thought_chunk":
            self.emit(kind="thought", text=getattr(update.content, "text", ""))
        elif kind == "tool_call":
            self._turn["tools"] = self._turn.get("tools", 0) + 1
            self.emit(kind="tool", id=update.tool_call_id, title=update.title or "tool",
                      status=update.status or "pending", detail=tool_detail(update))
        elif kind == "tool_call_update":
            self.emit(kind="tool_update", id=update.tool_call_id, title=update.title,
                      status=update.status, detail=tool_detail(update))
        elif kind == "plan":
            self.emit(kind="plan", entries=[{"text": getattr(e, "content", ""),
                                             "status": getattr(e, "status", "")} for e in update.entries])
        elif kind == "usage_update":
            self.emit(kind="usage", usage=_dump(update))
        elif kind == "config_option_update":
            self._read_config(_dump(update).get("configOptions") or [])
            self.emit(kind="options", options=self.options())

    async def request_permission(self, session_id, tool_call, options, **kw):
        rid = uuid.uuid4().hex[:10]
        request = {"id": rid, "title": tool_call.title or "tool call", "detail": tool_detail(tool_call),
                   "command": command_text(tool_call),
                   "options": [{"id": o.option_id, "name": o.name, "kind": o.kind} for o in options]}
        valid = {o.option_id for o in options}
        if self.auto_answer is not None:
            try:
                auto = self.auto_answer(request)
            except Exception:
                auto = None
            if auto in valid:
                return schema.RequestPermissionResponse(
                    outcome=schema.AllowedOutcome(outcome="selected", option_id=auto))
        self.emit(kind="permission", **request)
        asked = time.monotonic()
        choice = None
        try:
            if self.permission_handler is not None:
                fut = asyncio.ensure_future(self.permission_handler(request))
                self._pending[rid] = fut
                choice = await fut
        except asyncio.CancelledError:
            choice = None
        finally:
            self._pending.pop(rid, None)
            self._turn["waited"] = self._turn.get("waited", 0.0) + (time.monotonic() - asked)
        self.emit(kind="permission_done", id=rid, option=choice if choice in valid else None)
        if choice not in valid:
            return schema.RequestPermissionResponse(outcome=schema.DeniedOutcome(outcome="cancelled"))
        return schema.RequestPermissionResponse(
            outcome=schema.AllowedOutcome(outcome="selected", option_id=choice))

    # -- lifecycle ----------------------------------------------------------------
    async def start(self) -> None:
        if self._task is not None:
            return
        self._task = asyncio.create_task(self._run())
        await self._ready.wait()
        if self._error is not None:
            raise RuntimeError(f"{self.provider} agent failed to start: {self._error}") from self._error

    async def _run(self) -> None:
        t0 = time.monotonic()
        exe = shutil.which(self.argv[0]) or self.argv[0]
        self.emit(kind="status", text=f"starting {PROVIDERS.get(self.provider, {}).get('label', self.provider)} ...")
        try:
            if self.argv[0] in ("npx", "node") and not shutil.which(self.argv[0]):
                raise RuntimeError(NO_NODE)
            async with acp.spawn_agent_process(
                    self, exe, *self.argv[1:], cwd=self.cwd, env=child_env(self.env),
                    transport_kwargs={"limit": LINE_LIMIT}) as (conn, proc):
                self._conn = conn
                self.pid = proc.pid
                _LIVE.add(self)
                try:
                    init = await conn.initialize(
                        protocol_version=acp.PROTOCOL_VERSION,
                        client_capabilities=schema.ClientCapabilities(auth=schema.AuthCapabilities(terminal=True)),
                        client_info=schema.Implementation(name="ai-ify", version=__version__))
                    self.capabilities = _dump(init.agent_capabilities) or {}
                    self.auth_methods = [_method(m) for m in init.auth_methods or []]
                    try:
                        await self._open_session(conn)
                    except acp.RequestError as exc:
                        if not needs_signin(exc):
                            raise
                        self.startup_s = round(time.monotonic() - t0, 1)
                        self._needs_signin()           # Codex: no chat until signed in
                    else:
                        await self.apply_settings(self.settings)
                        self.startup_s = round(time.monotonic() - t0, 1)
                        self._announce_ready()
                    self._ready.set()
                    await self._stop.wait()
                finally:
                    self._conn = None
                    pid, self.pid = proc.pid, None
                    _LIVE.discard(self)
                    if proc.returncode is None:
                        kill_tree(pid)
        except BaseException as exc:                       # noqa: BLE001 - reported to the caller
            if not isinstance(exc, asyncio.CancelledError):
                self._error = exc
                self.emit(kind="error", text=f"agent stopped: {exc}")
        finally:
            self._ready.set()

    async def _open_session(self, conn) -> None:
        caps = self.capabilities.get("sessionCapabilities") or {}
        if self.resume_id:
            try:
                self._quiet = True
                if "resume" in caps:
                    resp = await conn.resume_session(session_id=self.resume_id, cwd=self.cwd)
                elif self.capabilities.get("loadSession"):
                    resp = await conn.load_session(cwd=self.cwd, session_id=self.resume_id)
                else:
                    raise RuntimeError("this agent cannot reopen earlier sessions")
                self.session_id = self.resume_id
                self._read_config((_dump(resp) or {}).get("configOptions") or [])
                return
            except Exception as exc:
                self.emit(kind="status", text=f"could not reopen session {self.resume_id[:8]}: {exc}; starting a new one")
            finally:
                self._quiet = False
        resp = _dump(await conn.new_session(cwd=self.cwd))
        self.session_id = resp["sessionId"]
        self._read_config(resp.get("configOptions") or [])

    def _announce_ready(self) -> None:
        self.emit(kind="ready", session=self.session_id, options=self.options(), startup=self.startup_s)

    # -- signing in ---------------------------------------------------------------
    def signin_methods(self) -> list[dict]:
        """The sign-in methods to offer: the subscription ones this provider lists."""
        wanted = PROVIDERS.get(self.provider, {}).get("signin")
        return [m for m in self.auth_methods if wanted is None or m["id"] in wanted]

    def _needs_signin(self) -> None:
        self.signed_out = True
        self.emit(kind="auth_required", provider=self.provider,
                  methods=[{k: m[k] for k in ("id", "name", "description", "type")}
                           for m in self.signin_methods()])

    def signin_argv(self, method_id: str) -> list[str]:
        """A terminal sign-in: the adapter's own command with the method's arguments."""
        m = next((m for m in self.auth_methods if m["id"] == method_id), None)
        if m is None or m["type"] != "terminal":
            raise ValueError(f"{method_id!r} is not a terminal sign-in")
        exe = shutil.which(self.argv[0]) or self.argv[0]
        return [exe, *self.argv[1:], *m["args"]]

    def signin_check_argv(self) -> list[str] | None:
        extra = PROVIDERS.get(self.provider, {}).get("signin_check")
        return [*self.argv, *extra] if extra else None

    async def authenticate(self, method_id: str) -> None:
        """A sign-in the adapter runs itself (Codex opens the browser), then the chat opens."""
        if self._conn is None:
            raise RuntimeError("agent is not running")
        await self._conn.authenticate(method_id=method_id)
        await self.after_signin()

    async def after_signin(self) -> None:
        """Open the chat if being signed out kept it closed; raises if still signed out."""
        if self._conn is None:
            raise RuntimeError("agent is not running")
        if self.session_id is None:
            try:
                await self._open_session(self._conn)
            except acp.RequestError as exc:
                if needs_signin(exc):
                    self._needs_signin()
                raise
            await self.apply_settings(self.settings)
            self.signed_out = False
            self._announce_ready()
        self.signed_out = False

    def _read_config(self, options: list) -> None:
        for opt in options:
            if not isinstance(opt, dict) or "id" not in opt:
                continue
            choices = [o.get("value") for o in opt.get("options", []) if isinstance(o, dict)]
            self.config[opt["id"]] = {"value": opt.get("currentValue"), "choices": choices,
                                      "name": opt.get("name", opt["id"])}

    @property
    def can_resume(self) -> bool:
        caps = self.capabilities.get("sessionCapabilities") or {}
        return bool("resume" in caps or self.capabilities.get("loadSession"))

    def options(self) -> dict:
        """``{model|effort|mode: {value, choices}}`` as this agent reports them."""
        out = {}
        for role, cid in self.keys.items():
            if cid in self.config:
                out[role] = {"value": self.config[cid]["value"], "choices": self.config[cid]["choices"]}
        return out

    async def set_option(self, role: str, value: str) -> None:
        cid = self.keys.get(role, role)
        if cid not in self.config:
            raise ValueError(f"{self.provider} has no {role} setting")
        if value not in self.config[cid]["choices"]:
            raise ValueError(f"{value!r} is not a {role} choice; choose from {self.config[cid]['choices']}")
        if self._conn is None:
            raise RuntimeError("agent is not running")
        resp = await self._conn.set_config_option(config_id=cid, session_id=self.session_id, value=value)
        self.config[cid]["value"] = value
        if resp is not None:
            self._read_config((_dump(resp) or {}).get("configOptions") or [])
        self.settings[role] = value

    async def apply_settings(self, settings: dict) -> None:
        for role in ("model", "effort", "mode"):
            value = settings.get(role)
            if value and value != "default" and self.options().get(role, {}).get("value") != value:
                try:
                    await self.set_option(role, value)
                except Exception as exc:
                    self.emit(kind="error", text=f"could not set {role}={value}: {exc}")

    async def send(self, text: str) -> dict:
        """Send one message; returns the turn summary also emitted as ``done``."""
        if self._conn is None:
            raise RuntimeError("agent is not running")
        if self.busy:
            raise RuntimeError("still answering the previous message")
        if self.session_id is None and self.signed_out:
            self._needs_signin()
            summary = {"stop": "auth_required", "first_words": None, "total": 0.0,
                       "waiting_on_you": 0.0, "tools": 0}
            self.emit(kind="done", **summary)
            return summary
        self.busy = True
        self._turn = {"t0": time.monotonic()}
        try:
            resp = await self._conn.prompt(session_id=self.session_id, prompt=[text_block(text)])
            stop = resp.stop_reason
        except acp.RequestError as exc:
            if needs_signin(exc):
                stop = "auth_required"                 # Claude: the chat opened, the message did not
                self._needs_signin()
            else:
                stop = f"error: {exc}"
                self.emit(kind="error", text=str(exc))
        except Exception as exc:
            stop = f"error: {exc}"
            self.emit(kind="error", text=str(exc))
        finally:
            self.busy = False
        summary = {"stop": stop, **self._timing()}
        self.emit(kind="done", **summary)
        return summary

    def _timing(self) -> dict:
        t = self._turn
        total = time.monotonic() - t.get("t0", time.monotonic())
        return {"first_words": round(t["first"], 1) if "first" in t else None, "total": round(total, 1),
                "waiting_on_you": round(t.get("waited", 0.0), 1), "tools": t.get("tools", 0)}

    async def cancel(self) -> None:
        for fut in list(self._pending.values()):
            if not fut.done():
                fut.cancel()
        if self._conn is not None and self.session_id:
            try:
                await self._conn.cancel(session_id=self.session_id)
            except Exception:
                pass

    async def close(self) -> None:
        if self.busy:
            await self.cancel()
        self._stop.set()
        if self._task is not None:
            try:
                await asyncio.wait_for(self._task, 15)
            except Exception:
                kill_tree(self.pid)
            self._task = None


# -- smoke command --------------------------------------------------------------

async def _smoke(provider: str, prompt: str, model: str | None, effort: str | None) -> int:
    def show(e):
        k = e["kind"]
        if k == "text":
            print(e["text"], end="", flush=True)
        elif k in ("ready", "done", "error", "permission", "status"):
            print(f"\n[{k}] " + " ".join(f"{a}={b}" for a, b in e.items() if a not in ("kind", "options")), flush=True)

    async def refuse(req):
        return None

    session = AcpSession(provider, cwd=work_dir("smoke"), on_event=show, permission_handler=refuse,
                         settings={"model": model, "effort": effort})
    await session.start()
    print("options:", {k: v["value"] for k, v in session.options().items()})
    summary = await session.send(prompt)
    await session.close()
    return 0 if summary["stop"] == "end_turn" else 1


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="One message through an ACP agent.")
    ap.add_argument("--provider", default="claude", choices=sorted(PROVIDERS))
    ap.add_argument("--model")
    ap.add_argument("--effort")
    ap.add_argument("prompt", nargs="?", default="Reply with exactly three words: the engine works.")
    a = ap.parse_args()
    sys.exit(asyncio.run(_smoke(a.provider, a.prompt, a.model, a.effort)))
