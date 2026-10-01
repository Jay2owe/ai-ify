"""FastAPI mount: the panel files, one websocket and a few POST routes.

    agent.mount(app)              # same as aiify.web.mount(agent, app, "/aiify")

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

POSTs must carry the header ``X-Aiify: 1``: a page on another site cannot add a
custom header without a CORS preflight, which these routes never grant.
"""
from __future__ import annotations

import asyncio
import contextlib
from pathlib import Path
from typing import TYPE_CHECKING

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


def mount(agent: "Agent", app, prefix: str = "/aiify") -> None:
    prefix = "/" + prefix.strip("/")
    router = APIRouter()

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
        await agent.cancel()

    @route("/api/settings")
    async def settings(data):
        keys = ("profile", "provider", "model", "effort", "mode")
        return {"info": await agent.configure(**{k: data[k] for k in keys if data.get(k)})}

    @route("/api/new")
    async def new(data):
        await agent.new_chat()

    @route("/api/console")
    async def open_console(data):
        return {"argv": await asyncio.to_thread(agent.open_console)}

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
