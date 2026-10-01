"""The app's local control port: 127.0.0.1 TCP, a token, a registry file.

Other parts of ai-ify register operation handlers on it (``action.*`` in
:mod:`aiify.actions`, ``ui.*`` in :mod:`aiify.ui_relay`). A handler takes the
request dict and returns a result, a :class:`~aiify.protocol.Reply`, or raises
:class:`~aiify.protocol.AiifyError`; anything else it raises becomes ``failed``.

    python -m aiify.control_port --demo     # a port with only ping/describe/state
"""
from __future__ import annotations

import asyncio
import json
import os
import secrets
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Awaitable, Callable

from .protocol import (
    MAX_LINE, PROTOCOL_VERSION, AiifyError, Reply, dumps, err, ok, registry_dir, serialize,
)

Handler = Callable[[dict], Awaitable[Any]]


def pid_alive(pid: int | None) -> bool:
    """Copied from ara ``adapters/base.py``."""
    if not pid:
        return False
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.windll.kernel32
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        STILL_ACTIVE = 259
        handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid))
        if not handle:
            return False
        try:
            code = wintypes.DWORD()
            if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
                return False
            return code.value == STILL_ACTIVE
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(int(pid), 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def list_apps(directory: Path | None = None) -> list[dict]:
    """Live apps from the registry; files left by dead processes are deleted."""
    directory = directory or registry_dir()
    out = []
    if not directory.is_dir():
        return out
    for path in sorted(directory.glob("*.json")):
        try:
            info = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(info, dict) or not pid_alive(info.get("pid")):
            try:
                path.unlink()
            except OSError:
                pass
            continue
        info["file"] = str(path)
        out.append(info)
    return out


class ControlPort:
    def __init__(self, app: str, *, directory: Path | None = None, host: str = "127.0.0.1"):
        if host not in ("127.0.0.1", "localhost", "::1"):
            raise ValueError("the control port only binds to the local machine")
        self.app = app
        self.host = host
        self.directory = directory
        self.token = secrets.token_hex(16)
        self.port: int | None = None
        self.handlers: dict[str, Handler] = {}
        self.describers: dict[str, Callable[[], Any]] = {}
        self.ui_attached: Callable[[], bool] = lambda: False
        self._server: asyncio.base_events.Server | None = None
        self._file: Path | None = None
        self.register("ping", self._ping)
        self.register("describe", self._describe)

    # -- registration ---------------------------------------------------------
    def register(self, op: str, handler: Handler) -> None:
        self.handlers[op] = handler

    def describer(self, level: str, fn: Callable[[], Any]) -> None:
        """``fn()`` fills ``levels[level]`` in ``describe``."""
        self.describers[level] = fn

    # -- built-in ops -----------------------------------------------------------
    async def _ping(self, req: dict) -> dict:
        return {"app": self.app, "pid": os.getpid(), "protocol": PROTOCOL_VERSION}

    async def _describe(self, req: dict) -> dict:
        levels = {}
        for level, fn in self.describers.items():
            try:
                value = fn()
                if asyncio.iscoroutine(value):
                    value = await value
            except Exception as exc:
                value = {"error": str(exc)}
            levels[level] = value
        return {"app": self.app, "protocol": PROTOCOL_VERSION, "ops": sorted(self.handlers),
                "ui_attached": bool(self.ui_attached()), "levels": levels}

    # -- dispatch ---------------------------------------------------------------
    async def handle_request(self, req: Any) -> dict:
        """Validate, authenticate and dispatch one request object."""
        if not isinstance(req, dict):
            return err(None, "invalid", "a request must be a JSON object")
        rid = req.get("id")
        if req.get("token") != self.token:
            return err(rid, "bad_token", "missing or wrong token")
        if "protocol" in req and req["protocol"] != PROTOCOL_VERSION:
            return err(rid, "invalid", f"protocol {req['protocol']!r} not supported (this app speaks {PROTOCOL_VERSION})")
        op = req.get("op")
        if not isinstance(op, str):
            return err(rid, "invalid", "op must be a string")
        handler = self.handlers.get(op)
        if handler is None:
            return err(rid, "unknown_op", f"unknown op {op!r}; available: {', '.join(sorted(self.handlers))}")
        try:
            result = await handler(req)
        except AiifyError as exc:
            return err(rid, exc.code, exc.message, **exc.extra)
        except Exception as exc:
            return err(rid, "failed", f"{type(exc).__name__}: {exc}")
        if isinstance(result, Reply):
            return ok(rid, result.result, **result.extra)
        return ok(rid, result)

    async def _client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            while True:
                try:
                    line = await reader.readline()
                except (asyncio.LimitOverrunError, ValueError):
                    reply = err(None, "invalid", "line too long")
                    writer.write((dumps(reply) + "\n").encode("utf-8"))
                    await writer.drain()
                    break
                if not line:
                    break
                if not line.strip():
                    continue
                try:
                    req = json.loads(line)
                except ValueError:
                    reply = err(None, "invalid", "not valid JSON")
                else:
                    reply = await self.handle_request(req)
                try:
                    text = dumps(reply)
                except (TypeError, ValueError) as exc:
                    text = dumps(err(reply.get("id"), "failed", f"reply could not be encoded: {exc}"))
                writer.write((text + "\n").encode("utf-8"))
                await writer.drain()
        except (ConnectionError, OSError):
            pass
        finally:
            try:
                writer.close()
            except Exception:
                pass

    # -- lifecycle --------------------------------------------------------------
    async def start(self) -> int:
        self._server = await asyncio.start_server(self._client, self.host, 0, limit=MAX_LINE)
        self.port = self._server.sockets[0].getsockname()[1]
        directory = self.directory or registry_dir()
        directory.mkdir(parents=True, exist_ok=True)
        self._file = directory / f"{_safe(self.app)}-{os.getpid()}.json"
        info = {"app": self.app, "pid": os.getpid(), "port": self.port, "token": self.token,
                "protocol": PROTOCOL_VERSION, "started": datetime.now().isoformat(timespec="seconds")}
        tmp = self._file.with_suffix(".tmp")
        tmp.write_text(json.dumps(info), encoding="utf-8")
        os.replace(tmp, self._file)
        return self.port

    async def stop(self) -> None:
        if self._server is not None:
            self._server.close()
            try:
                await asyncio.wait_for(self._server.wait_closed(), 5)
            except Exception:
                pass
            self._server = None
        if self._file is not None:
            try:
                self._file.unlink()
            except OSError:
                pass
            self._file = None


def _safe(name: str) -> str:
    return "".join(c if c.isalnum() or c in "-_." else "_" for c in name) or "app"


async def _demo() -> None:
    port = ControlPort("demo")
    counter = {"n": 0}

    async def state(req):
        counter["n"] += 1
        return {"demo": True, "calls": counter["n"]}

    port.register("state", state)
    number = await port.start()
    print(f"demo control port on 127.0.0.1:{number} (registry {port._file}); Ctrl+C to stop", flush=True)
    try:
        await asyncio.Event().wait()
    finally:
        await port.stop()


if __name__ == "__main__":
    if "--demo" in sys.argv:
        try:
            asyncio.run(_demo())
        except KeyboardInterrupt:
            pass
    else:
        print(__doc__)
