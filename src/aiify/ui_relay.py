"""Hand ``ui.*`` operations from the control port to the open page and back.

The page side is ``static/bridge.js`` (loaded by panel.js). It says hello over
the panel's websocket with the UI commands the page registered; the relay then
sends it ``ui.request`` messages and waits for the matching ``ui.reply``.
The most recently connected page with a bridge answers.
"""
from __future__ import annotations

import asyncio
import itertools
from typing import Any

from .protocol import AiifyError, Reply

UI_OPS = ("ui.do", "ui.tree", "ui.click", "ui.fill", "ui.select", "ui.scroll", "ui.read")
TIMEOUT = 15.0


class Page:
    def __init__(self, queue: asyncio.Queue, hello: dict):
        self.queue = queue
        self.tools: list[dict] = list(hello.get("tools") or [])
        self.url = hello.get("url", "")
        self.title = hello.get("title", "")
        self.changed = asyncio.Event()


class UiRelay:
    def __init__(self, timeout: float = TIMEOUT):
        self.timeout = timeout
        self.pages: list[Page] = []
        self._ids = itertools.count(1)
        self._waiting: dict[str, tuple[Page, asyncio.Future]] = {}

    # -- pages ------------------------------------------------------------------
    @property
    def attached(self) -> bool:
        return bool(self.pages)

    @property
    def page(self) -> Page | None:
        return self.pages[-1] if self.pages else None

    def _find(self, queue) -> Page | None:
        return next((p for p in self.pages if p.queue is queue), None)

    def on_hello(self, msg: dict, queue) -> None:
        old = self._find(queue)
        if old is not None:
            self.pages.remove(old)
        self.pages.append(Page(queue, msg))

    def on_tools(self, msg: dict, queue) -> None:
        page = self._find(queue)
        if page is not None:
            page.tools = list(msg.get("tools") or [])

    def on_changed(self, msg: dict, queue) -> None:
        page = self._find(queue)
        if page is not None:
            page.changed.set()

    def on_reply(self, msg: dict, queue) -> None:
        waiting = self._waiting.get(str(msg.get("id")))
        if waiting is not None and not waiting[1].done():
            waiting[1].set_result(msg)

    def drop(self, queue) -> None:
        page = self._find(queue)
        if page is None:
            return
        self.pages.remove(page)
        for rid, (p, fut) in list(self._waiting.items()):
            if p is page and not fut.done():
                fut.set_exception(AiifyError("no_ui", "the page closed before it answered"))

    def handlers(self) -> dict:
        return {"bridge.hello": self.on_hello, "bridge.tools": self.on_tools,
                "bridge.changed": self.on_changed, "ui.reply": self.on_reply}

    # -- requests ---------------------------------------------------------------
    async def request(self, op: str, fields: dict | None = None, timeout: float | None = None) -> dict:
        """Send one operation to the page; returns its reply (``ok`` true) or raises."""
        page = self.page
        if page is None:
            raise AiifyError("no_ui", "no window is attached to this app (backend actions still work)")
        rid = f"u{next(self._ids)}"
        fut = asyncio.get_running_loop().create_future()
        self._waiting[rid] = (page, fut)
        page.queue.put_nowait({"kind": "ui.request", "id": rid, "op": op, **(fields or {})})
        try:
            reply = await asyncio.wait_for(fut, timeout or self.timeout)
        except asyncio.TimeoutError:
            raise AiifyError("timeout", f"the page did not answer {op} in time") from None
        finally:
            self._waiting.pop(rid, None)
        if not reply.get("ok"):
            extra = {k: v for k, v in reply.items()
                     if k not in ("type", "id", "ok", "code", "error", "result")}
            raise AiifyError(reply.get("code") or "failed", reply.get("error") or f"{op} failed", **extra)
        return reply

    # -- control-port ops ---------------------------------------------------------
    def register(self, port) -> None:
        for op in UI_OPS:
            port.register(op, self._op(op))
        port.register("screenshot", self._screenshot)
        port.register("wait", self._wait)
        port.describer("ui_commands", self.describe)

    def describe(self) -> dict:
        page = self.page
        if page is None:
            return {"attached": False, "commands": [],
                    "hint": "no window open: ui.* ops answer no_ui"}
        return {"attached": True, "page": page.title or page.url,
                "commands": [{k: t.get(k) for k in ("name", "description", "inputSchema") if k in t}
                             for t in page.tools],
                "hint": "ui.do NAME key=value for these; ui.tree for every control (refs go stale after changes)"}

    def _op(self, op: str):
        async def handler(req: dict) -> Any:
            fields = {k: v for k, v in req.items() if k not in ("protocol", "token", "id", "op")}
            if op == "ui.do" and not isinstance(fields.get("name"), str):
                raise AiifyError("invalid", "ui.do needs a command name")
            if op in ("ui.click", "ui.fill", "ui.select", "ui.read") and not isinstance(fields.get("target"), str):
                raise AiifyError("invalid", f"{op} needs a target ref (from ui.tree)")
            reply = await self.request(op, fields, timeout=req.get("timeout") if isinstance(
                req.get("timeout"), (int, float)) else None)
            extra = {"screen_changed": True} if reply.get("screen_changed") else {}
            return Reply(reply.get("result"), extra)
        return handler

    async def _screenshot(self, req: dict) -> Any:
        raise AiifyError("not_supported", "screenshots of web pages are not supported; use ui.tree or ui.read")

    async def _wait(self, req: dict) -> Any:
        page = self.page
        if page is None:
            raise AiifyError("no_ui", "no window is attached to this app")
        timeout = req.get("timeout", 10)
        if not isinstance(timeout, (int, float)) or timeout <= 0:
            raise AiifyError("invalid", "timeout must be a positive number of seconds")
        page.changed.clear()
        try:
            await asyncio.wait_for(page.changed.wait(), min(float(timeout), 110.0))
            changed = True
        except asyncio.TimeoutError:
            changed = False
        state = None
        try:
            state = (await self.request("ui.state", timeout=3)).get("result")
        except AiifyError:
            pass
        return {"changed": changed, "state": state}

    async def page_state(self) -> dict | None:
        """What the page reports as on screen (its setState hook), or None."""
        if self.page is None:
            return None
        try:
            result = (await self.request("ui.state", timeout=3)).get("result")
        except AiifyError:
            return None
        return result if isinstance(result, dict) else ({"page": result} if result is not None else None)
