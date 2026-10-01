"""The public ``Agent``: one app's control port, actions, profiles and chat.

    from aiify import Agent, Profile, When

    agent = Agent(app="CircadianWorkbench", actions=ACTION_REGISTRY,
                  profiles={"analyst": Profile(model="opus", effort="high")},
                  state=lambda: {"view": current_view()})
    agent.mount(fastapi_app)          # panel + websocket + control port, tied to the app's lifespan
"""
from __future__ import annotations

import asyncio
import collections
import contextlib
import json
import re
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from . import accounts as accounts_mod
from . import console as console_mod
from .actions import ActionHost
from .control_port import ControlPort
from .engine import PROVIDERS, AcpSession, needs_signin, work_dir
from .policy import Policy
from .profile import Launch, Profile, Turn, When, resolve
from .prompting import build_message, command_for
from .protocol import AiifyError, serialize
from .signin import LoginProcess
from .ui_relay import UiRelay
from .usage import WARN_AT, UsageTracker, check_claude_usage

APPROVAL_WAIT = 90.0          # seconds an action approval card waits (the aiify command times out at 120)
SIGNIN_WAIT = 600.0          # seconds a sign-in may take before it is given up
HISTORY = 2000
PYTHON_EXE = re.compile(r"^(python[\d.]*w?|py|pyw)(\.exe)?$")


def split_commands(cmd: str) -> list[str] | None:
    """Split a shell line on unquoted ``;``, ``&&`` and newlines.

    Returns ``None`` when the line holds anything else a shell would act on
    (pipes, redirects, a lone ``&`` other than PowerShell's leading call operator,
    backticks, ``$(``), so such a line is always shown to the person.
    """
    segments, buf, quote, i = [], [], None, 0
    while i < len(cmd):
        c = cmd[i]
        if quote:
            if c == quote:
                quote = None
            elif quote == '"' and (c == "`" or cmd.startswith("$(", i)):
                return None                              # expands inside PowerShell double quotes
            buf.append(c)
        elif c in "'\"":
            quote = c
            buf.append(c)
        elif c in ";\n\r" or cmd.startswith("&&", i):
            segments.append("".join(buf))
            buf = []
            i += 2 if c == "&" else 1
            continue
        elif c == "&" and not "".join(buf).strip():
            pass                                         # PowerShell call operator at the start
        elif c in "|<>&`" or cmd.startswith("$(", i):
            return None
        else:
            buf.append(c)
        i += 1
    if quote:
        return None
    segments.append("".join(buf))
    segments = [seg.strip() for seg in segments if seg.strip()]
    return segments or None


class Agent:
    """Everything an app needs for an embedded agent.

    ``actions``: anything :func:`aiify.actions.as_source` accepts (a dispatch
    function pair, an ActionSpec registry, a dict of functions) or ``None``.
    ``guide``: text, a callable returning text, or an object with ``read()``.
    ``state``: a callable returning a JSON-able dict of what the app shows now.
    ``rules``: :class:`When` rules for every profile (profiles can add their own).
    ``instructions``: text (or callable of state) for every profile.
    ``engine_argv``: ``{provider: argv}`` to replace the adapter command (tests).
    ``limit_warning``: fraction of a subscription limit at which its bar warns.
    ``codex_accounts``: a :class:`aiify.accounts.CodexAccounts`, ``None`` for no
    account picker, or ``"auto"`` (the picker appears when codex-profiles is installed).
    ``limit_check_every``: seconds between Claude ``/usage`` checks after messages
    (a separate session, no tokens); ``None`` turns them off.
    ``launches``: ``{name: Launch}``, ways into the assistant from the app's buttons,
    each with its own context (see :class:`aiify.Launch`).

    ``rules`` and every context function receive a :class:`aiify.Turn`: what was
    typed, the app state, the agent's settings and the launch that started the chat.
    """

    def __init__(self, app: str, *, actions: Any = None, guide: Any = "",
                 profiles: Mapping[str, Profile] | None = None, profile: str | None = None,
                 state: Callable[[], dict] | None = None, rules: Sequence[When] = (),
                 instructions: Any = "", cwd: str | Path | None = None, prewarm: bool = False,
                 auto_allow_app_command: bool = True, command: str | None = None,
                 engine_argv: Mapping[str, list[str]] | None = None,
                 limit_warning: float = WARN_AT, codex_accounts: Any = "auto",
                 limit_check_every: float | None = 600,
                 launches: Mapping[str, Launch] | None = None):
        self.app = app
        self.profiles = dict(profiles or {"default": Profile()})
        self.profile_name = profile if profile in self.profiles else next(iter(self.profiles))
        self.guide = guide
        self.state_fn = state
        self.rules = list(rules)
        self.instructions = instructions
        self.cwd = Path(cwd) if cwd else None
        self.prewarm = prewarm
        self.auto_allow_app_command = auto_allow_app_command
        self.command = command or command_for(app)
        self.engine_argv = dict(engine_argv or {})
        self.provider = self.profile.provider
        self.settings = self.profile.settings()
        self.ui_state: dict = {}
        self.launches = dict(launches or {})
        for name, spec in self.launches.items():
            if spec.profile is not None and spec.profile not in self.profiles:
                raise ValueError(f"launch {name!r} names unknown profile {spec.profile!r}")
        self.launch_name: str | None = None      # the launch that started this chat
        self.launch_data: Any = None
        self._launch_new = False                  # its context is still to be told to the agent

        self.port = ControlPort(app)
        self.relay = UiRelay()
        self.relay.register(self.port)
        self.port.ui_attached = lambda: self.relay.attached
        self.port.register("state", self._op_state)
        self.actions = ActionHost(actions, self.profile.policy(), ask_user=self._ask_user) \
            if actions is not None else None
        if self.actions is not None:
            self.actions.register(self.port)

        self.session: AcpSession | None = None
        self.busy = False
        self.loop: asyncio.AbstractEventLoop | None = None
        self.history: collections.deque = collections.deque(maxlen=HISTORY)
        self._seq = 0
        self._subscribers: set[asyncio.Queue] = set()
        self._waiting: dict[str, asyncio.Future] = {}
        self._first = True
        self._stale = False                     # the console may have added turns
        self._session_lock: asyncio.Lock | None = None
        self._thread: threading.Thread | None = None
        self._turn_task: asyncio.Task | None = None
        self.started = False
        self.page_handlers: dict[str, Callable[[dict, Any], Any]] = dict(self.relay.handlers())
        self.usage = UsageTracker(limit_warning)
        if codex_accounts == "auto":
            codex_accounts = accounts_mod.CodexAccounts() if accounts_mod.executable() else None
        self.accounts: accounts_mod.CodexAccounts | None = codex_accounts
        self._pending_account: str | None = None
        self.limit_check_every = limit_check_every
        self._last_limit_check = 0.0
        self._limit_task: asyncio.Task | None = None
        self.signin: dict | None = None          # {provider, methods, waiting} while signed out
        self._signin_task: asyncio.Task | None = None
        self._login: LoginProcess | None = None
        self._unsent: str | None = None          # the message that met "sign in first"

    # -- configuration ----------------------------------------------------------------
    @property
    def profile(self) -> Profile:
        return self.profiles[self.profile_name]

    def guide_text(self) -> str:
        g = self.guide
        try:
            if hasattr(g, "read") and callable(g.read):
                g = g.read()
            elif callable(g):
                g = g()
        except Exception as exc:
            return f"(the app guide could not be read: {exc})"
        return str(g or "")

    def instructions_text(self, state: dict) -> str:
        if callable(self.instructions):
            try:
                return str(self.instructions(state) or "")
            except Exception as exc:
                return f"(the app's instructions could not be built: {exc})"
        return str(self.instructions or "")

    def current_state(self) -> dict:
        state = dict(self.ui_state)
        if self.state_fn is not None:
            try:
                got = self.state_fn()
                state.update(got if isinstance(got, dict) else {"state": got})
            except Exception as exc:
                state["state_error"] = f"{type(exc).__name__}: {exc}"
        return serialize(state)

    # -- events ---------------------------------------------------------------------
    def emit(self, **event) -> None:
        """Record an event and push it to every open panel (thread-safe)."""
        loop = self.loop
        if loop is not None and loop.is_running():
            try:
                running = asyncio.get_running_loop()
            except RuntimeError:
                running = None
            if running is not loop:
                loop.call_soon_threadsafe(lambda: self._emit(event))
                return
        self._emit(event)

    def _emit(self, event: dict) -> None:
        self._seq += 1
        event = {"seq": self._seq, **serialize(event)}
        if event.get("kind") != "info":                 # a newly opened panel gets info() itself
            self.history.append(event)
        for q in list(self._subscribers):
            q.put_nowait(event)

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue()
        self._subscribers.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        self._subscribers.discard(q)

    def _on_engine_event(self, event: dict) -> None:
        if event.get("kind") == "auth_required":
            prev = self.signin or {}                      # a sign-in already under way stays
            self.signin = {"provider": event.get("provider"), "methods": event.get("methods") or [],
                           "waiting": prev.get("waiting"), "link": prev.get("link"),
                           "code": prev.get("code", False)}
            self.emit(**event)
            self.emit(kind="info", info=self.info())
        elif event.get("kind") in ("ready", "options"):
            self.emit(**event)
            self.emit(kind="info", info=self.info())
        elif event.get("kind") == "usage":
            self.emit(**event)
            if self.usage.from_usage_event(event.get("usage")):
                self.emit(kind="info", info=self.info())
        else:
            self.emit(**event)

    # -- lifecycle --------------------------------------------------------------------
    async def start(self) -> None:
        if self.started:
            return
        self.loop = asyncio.get_running_loop()
        self._session_lock = asyncio.Lock()
        await self.port.start()
        self.started = True
        asyncio.ensure_future(self._read_limits(accounts=True))
        if self.prewarm:
            self.warm()

    async def stop(self) -> None:
        self._stop_signin()
        for task in (self._limit_task,):
            if task is not None and not task.done():
                task.cancel()
                with contextlib.suppress(BaseException):
                    await task
        for fut in list(self._waiting.values()):
            if not fut.done():
                fut.cancel()
        if self.session is not None:
            await self.session.close()
            self.session = None
        if self.started:
            await self.port.stop()
        self.started = False

    def start_background(self) -> None:
        """For apps without an asyncio loop (Qt, scripts): run the agent on its own thread."""
        if self._thread is not None:
            return
        loop = asyncio.new_event_loop()
        ready = threading.Event()

        def run():
            asyncio.set_event_loop(loop)
            loop.run_until_complete(self.start())
            ready.set()
            loop.run_forever()

        self._thread = threading.Thread(target=run, name=f"aiify-{self.app}", daemon=True)
        self._thread.start()
        ready.wait(30)

    def stop_background(self) -> None:
        if self._thread is None or self.loop is None:
            return
        asyncio.run_coroutine_threadsafe(self.stop(), self.loop).result(30)
        self.loop.call_soon_threadsafe(self.loop.stop)
        self._thread.join(10)
        self._thread = None

    def mount(self, app, prefix: str = "/aiify", *, inject: Any = False,
              panel: Mapping[str, Any] | None = None) -> None:
        """Add the panel, websocket and routes to a FastAPI app, and start/stop with it.

        ``inject=True`` also adds the panel to every HTML page (or pass a function of
        the path that says which pages); ``panel`` sets its look, e.g.
        ``{"layout": "float", "opacity": 85}`` (see :func:`aiify.web.panel_tag`).
        """
        from .web import mount
        mount(self, app, prefix, inject=inject, panel=panel)

    # -- the session ------------------------------------------------------------------
    def work_folder(self) -> Path:
        if self.cwd is not None:
            self.cwd.mkdir(parents=True, exist_ok=True)
            return self.cwd
        return work_dir(self.app)

    async def _ensure_session_quietly(self) -> None:
        try:
            await self._ensure_session()
        except Exception:
            pass                                        # reported as an error event already

    async def _ensure_session(self) -> AcpSession:
        if self._session_lock is None:
            self._session_lock = asyncio.Lock()
        async with self._session_lock:
            if self.session is not None and not self._stale:
                return self.session
            resume = None
            if self.session is not None:                  # reopen after the console was used
                resume = self.session.session_id
                await self.session.close()
                self.session = None
            session = AcpSession(self.provider, cwd=self.work_folder(), on_event=self._on_engine_event,
                                 permission_handler=self._permission, session_id=resume,
                                 settings=self.settings, argv=self.engine_argv.get(self.provider),
                                 auto_answer=self._auto_answer if self.auto_allow_app_command else None)
            self.session = session
            try:
                await session.start()
            except Exception as exc:
                self.session = None
                self.emit(kind="error", text=str(exc))
                self.emit(kind="info", info=self.info())
                raise
            if resume and session.session_id == resume:
                self._first = False
            self._stale = False
            return session

    async def send(self, text: str, *, echo: bool = True) -> dict:
        """One message from the person: wrap it with state and rules, stream the reply.

        ``echo=False`` resends a message the chat already shows (after signing in).
        """
        text = (text or "").strip()
        if not text:
            raise AiifyError("invalid", "empty message")
        if self.busy:
            raise AiifyError("invalid", "still answering the previous message")
        self.busy = True
        if echo:
            self.emit(kind="user", text=text)
        self.emit(kind="info", info=self.info())
        try:
            try:
                session = await self._ensure_session()
            except Exception as exc:
                summary = {"stop": f"error: {exc}"}
                self.emit(kind="done", **summary)
                return summary
            await self.refresh_page_state()
            state = self.current_state()
            turn = self.turn(text, state)
            message = build_message(text, app=self.app, profile=self.profile, state=state,
                                    first=self._first, rules=self.rules, guide=self.guide_text(),
                                    command=self.command, ui=self.relay.attached,
                                    instructions=self.instructions_text(state), turn=turn,
                                    launch=self.launches.get(self.launch_name or ""),
                                    launch_new=self._launch_new)
            first, self._first = self._first, False
            launch_new, self._launch_new = self._launch_new, False
            summary = await session.send(message)
            if summary.get("stop") == "auth_required":
                self._first, self._launch_new = first, launch_new   # none of it arrived
                self._unsent = text
            return summary
        finally:
            self.busy = False
            self.emit(kind="info", info=self.info())
            await self._after_message()

    def turn(self, text: str = "", state: dict | None = None) -> Turn:
        """What context functions see for a message: text, state, settings, launch."""
        options = self.session.options() if self.session is not None and self.session.session_id else {}
        setting = lambda role: (options.get(role) or {}).get("value") or self.settings.get(role)
        return Turn(text=text, state=self.current_state() if state is None else state,
                    provider=self.provider, model=setting("model"), effort=setting("effort"),
                    mode=setting("mode"), profile=self.profile_name, launch=self.launch_name,
                    data=self.launch_data, first=self._first)

    async def launch(self, name: str, data: Any = None) -> dict:
        """Start the assistant the way the app's button ``name`` asks (see :class:`aiify.Launch`)."""
        spec = self.launches.get(name)
        if spec is None:
            raise AiifyError("invalid", f"unknown launch {name!r}")
        if self.busy:
            raise AiifyError("invalid", "still answering the previous message")
        if spec.profile is not None and spec.profile != self.profile_name:
            await self.configure(profile=spec.profile)         # a new chat
        elif spec.new_chat:
            await self.new_chat()
        self.launch_name, self.launch_data, self._launch_new = name, data, True
        roles = {r: getattr(spec, r) for r in ("model", "effort", "mode") if getattr(spec, r)}
        if roles:
            await self.configure(**roles)
        self.emit(kind="launch", name=name, label=spec.label or name)
        self.emit(kind="info", info=self.info())
        message = resolve(spec.message, self.turn(), "launch message").strip()
        if message:
            self.send_soon(message)
        return {"launch": name, "sent": bool(message)}

    def send_soon(self, text: str, *, echo: bool = True) -> None:
        """Start a message without waiting for the reply (web routes)."""
        if self.busy:
            raise AiifyError("invalid", "still answering the previous message")
        if not (text or "").strip():
            raise AiifyError("invalid", "empty message")
        self._turn_task = asyncio.ensure_future(self._send_logged(text, echo))

    async def _send_logged(self, text: str, echo: bool = True) -> None:
        try:
            await self.send(text, echo=echo)
        except AiifyError as exc:
            self.emit(kind="error", text=exc.message)
        except Exception as exc:                          # noqa: BLE001 - shown in the panel
            self.emit(kind="error", text=f"{type(exc).__name__}: {exc}")

    async def cancel(self) -> None:
        for fut in list(self._waiting.values()):
            if not fut.done():
                fut.set_result(None)
        if self.session is not None:
            await self.session.cancel()

    async def new_chat(self) -> None:
        await self.cancel()
        self._stop_signin()
        self.signin = None
        self._unsent = None
        self.launch_name, self.launch_data, self._launch_new = None, None, False
        if self.session is not None:
            await self.session.close()
            self.session = None
        self._first = True
        self._stale = False
        self.history.clear()
        self.emit(kind="reset")
        self.emit(kind="info", info=self.info())
        if self.prewarm or self._subscribers:
            self.warm()

    def warm(self) -> None:
        """Start the agent in the background so the pickers fill and the first reply is quicker."""
        if self.session is None and self.started:
            asyncio.ensure_future(self._ensure_session_quietly())

    async def configure(self, *, profile: str | None = None, provider: str | None = None,
                        **roles: str | None) -> dict:
        """Change profile / provider (starts a new chat) or model / effort / mode (live)."""
        restart = False
        if profile is not None and profile != self.profile_name:
            if profile not in self.profiles:
                raise AiifyError("invalid", f"unknown profile {profile!r}")
            self.profile_name = profile
            self.provider = self.profile.provider
            self.settings = self.profile.settings()
            if self.actions is not None:
                self.actions.policy = self.profile.policy()
            restart = True
        if provider is not None and provider != self.provider:
            if provider not in PROVIDERS and provider not in self.engine_argv:
                raise AiifyError("invalid", f"unknown provider {provider!r}")
            self.provider = provider
            self.settings = {}                            # model names differ between providers
            restart = True
        if restart:
            await self.new_chat()
        for role, value in roles.items():
            if role not in ("model", "effort", "mode") or not value:
                continue
            self.settings[role] = value
            if self.session is not None and self.session.session_id:
                try:
                    await self.session.set_option(role, value)
                except Exception as exc:
                    raise AiifyError("invalid", str(exc)) from exc
        info = self.info()
        self.emit(kind="info", info=info)
        return info

    # -- signing in ----------------------------------------------------------------------
    async def sign_in(self, method_id: str | None = None) -> dict:
        """Start signing in with a method the agent offered (the panel's Sign in card).

        A terminal method (Claude) runs the adapter's own login with no window: it
        opens the browser, its link is shown in the panel too, and a code pasted in
        the panel goes to it. An agent method (Codex) is run by the adapter, which
        opens the browser. Either way the message that met "sign in first" is resent.
        """
        s = self.session
        if self.signin is None or s is None:
            raise AiifyError("invalid", "already signed in")
        methods = {m["id"]: m for m in self.signin["methods"]}
        if method_id is None and len(methods) == 1:
            method_id = next(iter(methods))
        method = methods.get(method_id or "")
        if method is None:
            raise AiifyError("invalid", f"unknown sign-in method {method_id!r}")
        self._stop_signin()
        if method["type"] == "terminal":
            login = LoginProcess(s.signin_argv(method["id"]), cwd=str(self.work_folder()),
                                 on_link=self._signin_link)
            await login.start()
            self._login = login
            self._signin_task = asyncio.ensure_future(self._terminal_signin(s, login))
        else:
            self._signin_task = asyncio.ensure_future(self._agent_signin(s, method["id"]))
        self.signin.update(waiting=method["id"], link=None, code=method["type"] == "terminal")
        self.emit(kind="status", text="Your browser opened to sign in. The chat carries on once you have.")
        self.emit(kind="info", info=self.info())
        return {"waiting": method["id"]}

    async def send_signin_code(self, code: str) -> dict:
        """The code the sign-in page shows, typed into the panel."""
        if self._login is None or not (code or "").strip():
            raise AiifyError("invalid", "no sign-in is waiting for a code")
        await self._login.send_code(code)
        self.emit(kind="status", text="Checking the code...")
        return {"sent": True}

    def _signin_link(self, url: str) -> None:
        if self.signin is not None:
            self.signin["link"] = url
            self.emit(kind="info", info=self.info())

    def _stop_signin(self) -> None:
        if self._signin_task is not None and not self._signin_task.done():
            self._signin_task.cancel()
        self._signin_task = None
        if self._login is not None:
            self._login.stop()
            self._login = None

    def _signin_failed(self, text: str) -> None:
        if self.signin is not None:
            self.signin.update(waiting=None, link=None, code=False)
        self.emit(kind="error", text=text)
        self.emit(kind="info", info=self.info())

    async def _terminal_signin(self, s: AcpSession, login: LoginProcess) -> None:
        try:
            code = await asyncio.wait_for(login.wait(), SIGNIN_WAIT)
        except asyncio.TimeoutError:
            login.stop()
            code = None
        finally:
            if self._login is login:
                self._login = None
        if code == 0 and await self._finish_signin(s):
            return
        self._signin_failed("Signing in did not finish. Press Sign in to try again.")

    async def _agent_signin(self, s: AcpSession, method_id: str) -> None:
        try:
            await s.authenticate(method_id)
        except asyncio.CancelledError:
            raise
        except Exception as exc:                          # noqa: BLE001 - shown in the panel
            self._signin_failed("Signing in did not finish. Press Sign in to try again."
                                if needs_signin(exc) else f"Signing in failed: {exc}")
            return
        await self._finish_signin(s)

    async def _finish_signin(self, s: AcpSession | None) -> bool:
        """Signed in: open the chat if needed, clear the card and resend the waiting message."""
        if s is None or s is not self.session or self.signin is None:
            return False
        try:
            await s.after_signin()
        except Exception:                                 # noqa: BLE001 - still signed out
            return False
        self.signin = None
        self.emit(kind="signed_in", provider=s.provider)
        self.emit(kind="status", text="Signed in.")
        self.emit(kind="info", info=self.info())
        text, self._unsent = self._unsent, None
        if text and not self.busy:
            self.send_soon(text, echo=False)
        return True

    # -- limits and accounts ----------------------------------------------------------
    async def _read_limits(self, *, accounts: bool = False) -> None:
        """Codex limits from its session logs (and the saved accounts); file reads off the loop."""
        try:
            if accounts and self.accounts is not None:
                await asyncio.to_thread(self.accounts.refresh)
            changed = await asyncio.to_thread(self.usage.refresh_codex)
        except Exception:                                 # noqa: BLE001 - limits are best effort
            return
        if changed or accounts:
            self.emit(kind="info", info=self.info())

    async def _after_message(self) -> None:
        if self.provider == "codex":
            await self._read_limits()
        elif self.provider == "claude":
            self.check_claude_limits()
        pending, self._pending_account = self._pending_account, None
        if pending:
            try:
                await self._switch_account(pending)
            except AiifyError:
                pass                                      # shown in the panel already

    def check_claude_limits(self, *, force: bool = False) -> None:
        """Read Claude's limits with ``/usage`` in the background, at most every ``limit_check_every``."""
        if self.limit_check_every is None and not force:
            return
        if self._limit_task is not None and not self._limit_task.done():
            return
        if not force and time.time() - self._last_limit_check < (self.limit_check_every or 0):
            return
        self._last_limit_check = time.time()
        self._limit_task = asyncio.ensure_future(self._claude_limits())

    async def _claude_limits(self) -> None:
        windows = await check_claude_usage(work_dir("_limits"), self.engine_argv.get("claude"))
        if windows and self.usage.update(windows):
            self.emit(kind="info", info=self.info())

    async def request_account(self, identity: str) -> dict:
        """Use another saved Codex account: now if idle, else once the current message ends."""
        if self.accounts is None:
            raise AiifyError("not_supported", "Codex account switching needs codex-profiles")
        if self.busy:
            self._pending_account = identity
            self.emit(kind="status", text="Switching Codex account after this reply.")
            self.emit(kind="info", info=self.info())
            return {"pending": True}
        return await self._switch_account(identity)

    async def _switch_account(self, identity: str) -> dict:
        try:
            chosen = await asyncio.to_thread(self.accounts.switch, identity)
        except accounts_mod.ProfileError as exc:
            self.emit(kind="error", text=str(exc))
            self.emit(kind="info", info=self.info())
            raise AiifyError("failed", str(exc)) from exc
        self.usage.forget("codex")
        self.usage.update(await asyncio.to_thread(self.accounts.usage))
        if self.session is not None and self.provider == "codex":
            self._stale = True                            # the next message restarts Codex signed in as it
        self.emit(kind="status", text=f"Codex now uses {chosen['name']}.")
        self.emit(kind="info", info=self.info())
        return {"pending": False, "account": chosen}

    # -- approvals --------------------------------------------------------------------
    def _auto_answer(self, request: dict) -> str | None:
        """Let the agent run this app's own ``aiify`` command without a prompt.

        Allowed: one or more of this app's commands joined by ``;`` / ``&&`` /
        newlines, and nothing else - no pipes, redirects or other programs.
        What each command may do is still limited by the profile's action policy.
        ``--confirm`` (which skips an action's approval card) and ``raw`` requests
        always go to the person.
        """
        segments = split_commands(request.get("command") or "")
        if not segments or not all(self._own_command(seg) for seg in segments):
            return None
        for kind in ("allow_once", "allow_always"):
            for o in request.get("options", []):
                if o.get("kind") == kind:
                    return o["id"]
        return None

    def _own_command(self, segment: str) -> bool:
        m = re.match(r'^("[^"]+"|\S+)\s+(.*)$', segment, re.S)
        if not m:
            return False
        exe = m.group(1).strip('"').replace("\\", "/").rsplit("/", 1)[-1].lower()
        rest = m.group(2)
        app = re.escape(self.app)
        if PYTHON_EXE.match(exe):
            if not re.match(r"^-m\s+aiify\s", rest):
                return False
            rest = re.sub(r"^-m\s+aiify\s+", "", rest, count=1)
        elif exe not in ("aiify", "aiify.exe"):
            return False
        if re.search(r"(^|\s)(--confirm|raw)(\s|$)", rest):
            return False                                  # would skip the approval card
        return bool(re.match(rf"""^--app\s+(["']?){app}\1(\s|$)""", rest))

    async def _wait_answer(self, rid: str, timeout: float | None = None):
        fut = asyncio.get_running_loop().create_future()
        self._waiting[rid] = fut
        try:
            return await asyncio.wait_for(fut, timeout) if timeout else await fut
        except (asyncio.TimeoutError, asyncio.CancelledError):
            return None
        finally:
            self._waiting.pop(rid, None)

    async def _permission(self, request: dict) -> str | None:
        return await self._wait_answer(request["id"])

    async def _ask_user(self, name: str, params: dict, spec: dict) -> bool | None:
        """An action needs approval: show a card when a panel is open, else let the agent ask."""
        if not self._subscribers:
            return None
        rid = "act-" + uuid.uuid4().hex[:8]
        detail = {k: v for k, v in spec.items() if k not in ("name", "summary", "params", "ok")}
        lines = [spec.get("summary") or ""]
        if params:
            lines.append("with " + json.dumps(serialize(params)))
        if detail:
            lines.append(json.dumps(serialize(detail))[:600])
        self.emit(kind="permission", id=rid, source="action", title=f"Run {name}?",
                  detail="\n".join(x for x in lines if x),
                  options=[{"id": "yes", "name": "Run it", "kind": "allow_once"},
                           {"id": "no", "name": "Don't", "kind": "reject_once"}])
        answer = await self._wait_answer(rid, APPROVAL_WAIT)
        self.emit(kind="permission_done", id=rid, option=answer)
        if answer is None:
            return None
        return answer == "yes"

    def answer(self, request_id: str, option: str | None) -> bool:
        fut = self._waiting.get(request_id)
        if fut is None or fut.done():
            return False
        fut.set_result(option)
        return True

    # -- console ----------------------------------------------------------------------
    def console_status(self) -> dict:
        s = self.session
        if s is None or not s.session_id:
            return {"available": False, "reason": "send a message first"}
        if self.provider not in ("claude", "codex"):
            return {"available": False, "reason": f"no console for {self.provider}"}
        try:
            console_mod.vendor_argv(self.provider, s.session_id)
        except (FileNotFoundError, ValueError) as exc:
            return {"available": False, "reason": str(exc)}
        return {"available": True, "reason": ""}

    def open_console(self, launcher=None) -> list[str]:
        status = self.console_status()
        if not status["available"]:
            raise AiifyError("not_supported", status["reason"])
        argv = console_mod.open_console(self.provider, self.session.session_id, str(self.work_folder()),
                                        app=self.app, launcher=launcher)
        self._stale = True
        self.emit(kind="status", text="Opened this conversation in a console. Your next message "
                                      "here picks up what was said there.")
        return argv

    # -- the page (stage 05 adds the UI relay) ------------------------------------------
    async def on_page_message(self, msg: dict, page: Any = None) -> None:
        handler = self.page_handlers.get(msg.get("type", ""))
        if handler is not None:
            result = handler(msg, page)
            if asyncio.iscoroutine(result):
                await result

    def on_page_closed(self, page: Any) -> None:
        """A panel's websocket closed: the UI relay forgets that page."""
        self.relay.drop(page)

    async def refresh_page_state(self) -> None:
        """Ask the open page what it shows (its ``aiify.setState`` hook)."""
        got = await self.relay.page_state()
        self.ui_state = got or {}

    async def _op_state(self, req: dict) -> dict:
        await self.refresh_page_state()
        return self.current_state()

    def info(self) -> dict:
        s = self.session
        return {
            "app": self.app,
            "profile": self.profile_name,
            "profiles": [{"name": n, "label": p.label or n, "provider": p.provider}
                         for n, p in self.profiles.items()],
            "provider": self.provider,
            "providers": [{"name": n, "label": v["label"]} for n, v in PROVIDERS.items()],
            "options": s.options() if s is not None and s.session_id else {},
            "settings": dict(self.settings),
            "session": s.session_id if s is not None else None,
            "ready": bool(s is not None and s.session_id),
            "busy": self.busy,
            "console": self.console_status(),
            "port": self.port.port,
            "limits": self.usage.snapshot(),
            "accounts": self._accounts_info(),
            "signin": dict(self.signin) if self.signin is not None else None,
            "launches": [{"name": n, "label": l.label or n} for n, l in self.launches.items()],
            "launch": ({"name": self.launch_name,
                        "label": self.launches[self.launch_name].label or self.launch_name}
                       if self.launch_name in self.launches else None),
        }

    def _accounts_info(self) -> dict | None:
        if self.accounts is None or self.provider != "codex" or len(self.accounts.choices) < 2:
            return None
        return {**self.accounts.info(), "pending": self._pending_account}
