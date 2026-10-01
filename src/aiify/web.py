"""FastAPI mount: the panel files, one websocket and a few POST routes.

    agent.mount(app)              # same as aiify.web.mount(agent, app, "/aiify")
    agent.mount(app, inject=True, panel={"layout": "float"})   # also adds the panel to every page

Routes (all under the prefix):
    GET  /panel.js, /panel.css, ...   the drop-in panel (static files)
    WS   /ws                          chat events out; page messages in (stage 05)
    GET  /api/info                    profiles, provider, options, session, console
    POST /api/send {text}             start a message
    POST /api/answer {id, option}     answer a permission or action approval
    POST /api/cancel                  stop the running message
    POST /api/settings {profile?, provider?, model?, effort?, mode?}
    POST /api/new                     new chat
    POST /api/console                 open the conversation in a terminal
    POST /api/account {id}            use another saved Codex account (after the running message)
    POST /api/signin {method} | {code}   sign in, or pass the code the sign-in page shows
    POST /api/launch {name, data?, attach?}  start the chat the way one of the app's buttons asks
    POST /api/queue {text}            send after the current reply (Agent(queue=True))
    POST /api/schedule {text, at}     send at an ISO time (Agent(schedule=True))
    POST /api/unqueue {id}            drop a queued or scheduled message
    POST /api/attach {name, text | data_url}   attach to the next message; /api/detach {id}

POSTs must carry the header ``X-Aiify: 1``: a page on another site cannot add a
custom header without a CORS preflight, which these routes never grant.
"""
from __future__ import annotations

import asyncio
import contextlib
import html
from pathlib import Path
from typing import TYPE_CHECKING, Callable, Mapping

from fastapi import APIRouter, Request, WebSocket, WebSocketDisconnect     # web.py needs the [web] extra
from fastapi.responses import FileResponse, JSONResponse, Response

from .protocol import AiifyError

if TYPE_CHECKING:
    from .agent import Agent

STATIC = Path(__file__).with_name("static")
TYPES = {".js": "text/javascript", ".css": "text/css", ".json": "application/json",
         ".txt": "text/plain", ".md": "text/plain", ".svg": "image/svg+xml"}


def _static_file(name: str) -> Path | None:
    try:
        path = (STATIC / name).resolve()
        path.relative_to(STATIC.resolve())
    except (ValueError, OSError):
        return None
    return path if path.is_file() else None


def _same_origin(headers) -> bool:
    origin = headers.get("origin")
    if not origin:
        return True                                     # not a browser, or same-origin navigation
    host = headers.get("host", "")
    return origin.split("://", 1)[-1] == host


PANEL_OPTIONS = ("layout", "target", "opacity", "launcher", "accent", "font", "theme", "title", "open")
SKIP_PATHS = ("/docs", "/redoc", "/openapi.json")


def panel_tag(prefix: str = "/aiify", **options) -> str:
    """The ``<script>`` tag that adds the panel, with its look as ``data-`` attributes.

    ``panel_tag(layout="float", opacity=85, accent="#2b6cb0")``; the options are
    listed at the top of panel.js.
    """
    unknown = set(options) - set(PANEL_OPTIONS)
    if unknown:
        raise ValueError(f"unknown panel option(s) {sorted(unknown)}; choose from {list(PANEL_OPTIONS)}")
    attrs = "".join(f' data-{k}="{html.escape(str(v).lower() if isinstance(v, bool) else str(v), quote=True)}"'
                    for k, v in options.items() if v is not None)
    return f'<script src="{"/" + prefix.strip("/")}/panel.js" defer{attrs}></script>'


class InjectPanel:
    """ASGI middleware: adds the panel tag before ``</body>`` of the app's HTML pages.

    Skips pages that already load panel.js, compressed or streamed bodies too large
    to hold, the panel's own routes, FastAPI's docs pages, and any path for which
    ``where(path)`` is false.
    """
    LIMIT = 5 * 1024 * 1024

    def __init__(self, app, tag: str, prefix: str, where: Callable[[str], bool] | None = None):
        self.app, self.tag, self.prefix, self.where = app, tag.encode(), prefix, where

    def _wanted(self, path: str) -> bool:
        if path.startswith(self.prefix + "/") or path.startswith(SKIP_PATHS):
            return False
        return self.where(path) if self.where is not None else True

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or not self._wanted(scope.get("path", "")):
            return await self.app(scope, receive, send)
        start: dict | None = None
        body: list[bytes] = []
        passing = False

        async def wrapped(message):
            nonlocal start, passing
            if passing:
                return await send(message)
            if message["type"] == "http.response.start":
                headers = {k.lower(): v for k, v in message.get("headers", [])}
                ctype = headers.get(b"content-type", b"")
                if not ctype.startswith(b"text/html") or b"content-encoding" in headers:
                    passing = True
                    return await send(message)
                start = message
                return
            body.append(message.get("body", b""))
            if message.get("more_body") and sum(map(len, body)) < self.LIMIT:
                return
            data = b"".join(body)
            if message.get("more_body"):                  # too large to hold: send unchanged
                passing = True
            elif b"/panel.js" not in data and b"</body>" in data:
                i = data.rfind(b"</body>")
                data = data[:i] + self.tag + data[i:]
            headers = [(k, v) for k, v in start.get("headers", []) if k.lower() != b"content-length"]
            if not passing:
                headers.append((b"content-length", str(len(data)).encode()))
            await send({**start, "headers": headers})
            await send({"type": "http.response.body", "body": data, "more_body": bool(message.get("more_body"))})

        await self.app(scope, receive, wrapped)


def mount(agent: "Agent", app, prefix: str = "/aiify", *, inject: bool | Callable[[str], bool] = False,
          panel: Mapping[str, object] | None = None) -> None:
    """``inject``: add the panel to the app's HTML pages (True, or a function of the
    path that says which). ``panel``: its look, as for :func:`panel_tag`."""
    prefix = "/" + prefix.strip("/")
    router = APIRouter()
    if inject:
        app.add_middleware(InjectPanel, tag=panel_tag(prefix, **dict(panel or {})), prefix=prefix,
                           where=inject if callable(inject) else None)
    elif panel:
        panel_tag(prefix, **dict(panel))                  # check the options even when unused

    def fail(exc: Exception, status: int = 400):
        message = exc.message if isinstance(exc, AiifyError) else str(exc)
        code = exc.code if isinstance(exc, AiifyError) else "failed"
        return JSONResponse({"ok": False, "code": code, "error": message}, status_code=status)

    async def body_of(request: Request) -> dict:
        if request.headers.get("x-aiify") != "1" or not _same_origin(request.headers):
            raise PermissionError("missing X-Aiify header or wrong origin")
        try:
            data = await request.json()
        except ValueError:
            data = {}
        return data if isinstance(data, dict) else {}

    def route(path: str):
        def wrap(fn):
            async def handler(request: Request):
                try:
                    data = await body_of(request)
                except PermissionError as exc:
                    return fail(exc, 403)
                try:
                    result = await fn(data)
                except Exception as exc:                # noqa: BLE001 - becomes a JSON error
                    return fail(exc)
                return JSONResponse({"ok": True, **(result or {})})
            router.add_api_route(prefix + path, handler, methods=["POST"], include_in_schema=False)
            return fn
        return wrap

    @router.get(prefix + "/api/info", include_in_schema=False)
    async def info():
        return agent.info()

    @route("/api/send")
    async def send(data):
        agent.send_soon(str(data.get("text") or ""))

    @route("/api/answer")
    async def answer(data):
        return {"answered": agent.answer(str(data.get("id")), data.get("option"))}

    @route("/api/cancel")
    async def cancel(data):
        await agent.cancel(unqueue=True)

    @route("/api/settings")
    async def settings(data):
        keys = ("profile", "provider", "model", "effort", "mode")
        return {"info": await agent.configure(by_person=True, **{k: data[k] for k in keys if data.get(k)})}

    @route("/api/new")
    async def new(data):
        await agent.new_chat()

    @route("/api/console")
    async def open_console(data):
        return {"argv": await asyncio.to_thread(agent.open_console)}

    def page_attachment(item) -> dict:
        if not isinstance(item, dict):
            raise AiifyError("invalid", "an attachment is {name, text} or {name, data_url}")
        return {k: item[k] for k in ("name", "text", "data_url") if item.get(k) is not None}

    @route("/api/launch")
    async def launch(data):
        attach = [page_attachment(a) for a in (data.get("attach") or [])]
        return await agent.launch(str(data.get("name") or ""), data.get("data"), attach)

    def feature(name: str) -> None:
        if not agent.features.get(name):
            raise AiifyError("not_supported", f"this app has not turned on {name}")

    @route("/api/queue")
    async def queue(data):
        feature("queue")
        return agent.queue_message(str(data.get("text") or ""))

    @route("/api/schedule")
    async def schedule(data):
        feature("schedule")
        return agent.schedule_message(str(data.get("text") or ""), str(data.get("at") or ""))

    @route("/api/unqueue")
    async def unqueue(data):
        return agent.remove_pending(str(data.get("id") or ""))

    @route("/api/attach")
    async def attach(data):
        return agent.attach(**page_attachment(data))

    @route("/api/detach")
    async def detach(data):
        return agent.detach(str(data.get("id") or ""))

    @route("/api/signin")
    async def signin(data):
        if data.get("code"):
            return await agent.send_signin_code(str(data["code"]))
        return await agent.sign_in(data.get("method"))

    @route("/api/account")
    async def account(data):
        return await agent.request_account(str(data.get("id") or ""))

    @router.websocket(prefix + "/ws")
    async def ws(socket: WebSocket):
        if not _same_origin(socket.headers):
            await socket.close(code=1008)
            return
        await socket.accept()
        queue = agent.subscribe()
        try:
            await socket.send_json({"kind": "hello", "info": agent.info(), "history": list(agent.history)})
            agent.warm()

            async def outgoing():
                while True:
                    await socket.send_json(await queue.get())

            async def incoming():
                while True:
                    msg = await socket.receive_json()
                    if isinstance(msg, dict):
                        await agent.on_page_message(msg, queue)

            tasks = [asyncio.ensure_future(outgoing()), asyncio.ensure_future(incoming())]
            done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for t in pending:
                t.cancel()
            for t in done:
                exc = t.exception()
                if exc and not isinstance(exc, (WebSocketDisconnect, RuntimeError)):
                    raise exc
        except WebSocketDisconnect:
            pass
        finally:
            agent.unsubscribe(queue)
            agent.on_page_closed(queue)

    @router.get(prefix + "/{name:path}", include_in_schema=False)
    async def static(name: str):
        path = _static_file(name)
        if path is None:
            return Response(status_code=404)
        return FileResponse(path, media_type=TYPES.get(path.suffix, "application/octet-stream"),
                            headers={"Cache-Control": "no-cache"})

    app.include_router(router)
    _chain_lifespan(agent, app)


def _chain_lifespan(agent: "Agent", app) -> None:
    """Start the agent with the app and stop it after, keeping the app's own lifespan."""
    original = app.router.lifespan_context

    @contextlib.asynccontextmanager
    async def lifespan(a):
        await agent.start()
        try:
            async with original(a) as state:
                yield state
        finally:
            await agent.stop()

    app.router.lifespan_context = lifespan
