"""The app's own web routes as actions, found with no work from the developer.

FastAPI already describes every route (path, method, parameters, docstring). Each
JSON route becomes an action named ``route.<function name>``: routes that only
read (GET, HEAD) run freely; every other method asks the person first, like a
destructive action. Pages (routes answering HTML) are not actions; they are
listed for ``aiify how`` instead. Routes are called inside the app's process,
so nothing goes over the network.
"""
from __future__ import annotations

import asyncio
import inspect
import json
import re
from fnmatch import fnmatchcase
from typing import Any, Callable, Sequence
from urllib.parse import quote, urlencode

from .actions import _envelope_err, _envelope_ok

SKIP = ("/docs*", "/redoc*", "/openapi.json")
READS = ("GET", "HEAD")
RESULT_LIMIT = 20000
TIMEOUT = 110.0


def _deref(schema: dict, components: dict) -> dict:
    ref = (schema or {}).get("$ref", "")
    if ref.startswith("#/components/schemas/"):
        return components.get(ref.rsplit("/", 1)[-1], {})
    return schema or {}


def _kind(schema: dict) -> str:
    if "type" in schema:
        return str(schema["type"])
    for key in ("anyOf", "oneOf"):
        kinds = [str(s.get("type")) for s in schema.get(key, []) if s.get("type") not in (None, "null")]
        if kinds:
            return kinds[0]
    return "any"


def _is_page(route) -> bool:
    cls = getattr(route, "response_class", None)
    name = getattr(cls, "__name__", "") if cls is not None else ""
    return name in ("HTMLResponse", "FileResponse")


class RouteSource:
    """``names`` / ``describe`` / ``run`` over the app's JSON routes."""

    def __init__(self, app, *, prefix: str = "/aiify", include: Sequence[str] = ("*",),
                 loop: Callable[[], Any] = lambda: None):
        self.app = app
        self.prefix = prefix.rstrip("/")
        self.include = list(include)
        self.loop = loop
        self._specs: dict[str, dict] | None = None
        self.pages: list[dict] = []

    # -- discovery ------------------------------------------------------------------
    def _wanted(self, path: str) -> bool:
        if path.startswith(self.prefix + "/") or path == self.prefix:
            return False
        if any(fnmatchcase(path, p) for p in SKIP):
            return False
        return any(fnmatchcase(path, p) for p in self.include)

    def specs(self) -> dict[str, dict]:
        if self._specs is not None:
            return self._specs
        try:
            from fastapi.routing import APIRoute
        except ImportError:                               # not a FastAPI app
            self._specs = {}
            return self._specs
        try:
            openapi = self.app.openapi()
        except Exception:                                 # noqa: BLE001 - parameters are a bonus
            openapi = {}
        components = (openapi.get("components") or {}).get("schemas", {})
        specs: dict[str, dict] = {}
        for route in getattr(self.app, "routes", []):
            if not isinstance(route, APIRoute) or not self._wanted(route.path):
                continue
            doc = (inspect.getdoc(route.endpoint) or "").strip()
            methods = sorted(m for m in route.methods if m != "OPTIONS")
            if _is_page(route):
                self.pages.append({"path": route.path, "summary": doc.splitlines()[0] if doc else "",
                                   "doc": doc})
                continue
            for method in methods:
                if method == "HEAD" and "GET" in methods:
                    continue
                op = ((openapi.get("paths") or {}).get(route.path) or {}).get(method.lower(), {})
                params = []
                for p in op.get("parameters", []):
                    params.append({"name": p["name"], "in": p.get("in", "query"),
                                   "required": bool(p.get("required")), "type": _kind(p.get("schema", {}))})
                body = ((op.get("requestBody") or {}).get("content") or {}).get("application/json", {})
                body_schema = _deref(body.get("schema", {}), components)
                whole_body = False
                if body_schema.get("properties"):
                    required = set(body_schema.get("required", []))
                    for pname, ps in body_schema["properties"].items():
                        params.append({"name": pname, "in": "body", "required": pname in required,
                                       "type": _kind(_deref(ps, components))})
                elif body:
                    whole_body = True
                    params.append({"name": "body", "in": "body", "required": bool(op.get("requestBody", {}).get("required")),
                                   "type": _kind(body_schema)})
                name = "route." + re.sub(r"\W+", "_", route.name or route.path).strip("_")
                if name in specs:
                    name = f"{name}_{method.lower()}"
                summary = doc.splitlines()[0] if doc else (op.get("summary") or f"{method} {route.path}")
                specs[name] = {"method": method, "path": route.path, "summary": summary, "doc": doc,
                               "params": params, "whole_body": whole_body,
                               "mutates": method not in READS, "destructive": method not in READS}
        self._specs = specs
        return specs

    # -- ActionSource ---------------------------------------------------------------
    def names(self) -> list[str]:
        return sorted(self.specs())

    def _row(self, name: str, spec: dict) -> dict:
        return {"name": name, "summary": f"{spec['summary']} ({spec['method']} {spec['path']})",
                "mutates": spec["mutates"], "destructive": spec["destructive"]}

    def describe(self, name: str | None = None) -> dict:
        specs = self.specs()
        if name is None:
            return {"actions": [self._row(n, specs[n]) for n in self.names()]}
        if name not in specs:
            return _envelope_err("unknown_action", f"unknown action {name!r}")
        spec = specs[name]
        return {**self._row(name, spec), "doc": spec["doc"],
                "params": [{k: p[k] for k in ("name", "required", "type")} for p in spec["params"]]}

    def run(self, name: str, params: dict, *, confirm: bool = False) -> dict:
        spec = self.specs().get(name)
        if spec is None:
            return _envelope_err("unknown_action", f"unknown action {name!r}")
        loop = self.loop()
        if loop is None or not loop.is_running():
            return _envelope_err("failed", "the app is not running")
        params = dict(params or {})
        known = {p["name"] for p in spec["params"]}
        unknown = sorted(set(params) - known)
        if unknown:
            return _envelope_err("invalid", f"unknown parameter(s) {unknown}; see action.describe {name}")
        missing = [p["name"] for p in spec["params"] if p["required"] and p["name"] not in params]
        if missing:
            return _envelope_err("invalid", f"missing parameter(s) {missing}")
        path, query, body = spec["path"], {}, None
        for p in spec["params"]:
            if p["name"] not in params:
                continue
            value = params[p["name"]]
            if p["in"] == "path":
                path = path.replace("{" + p["name"] + "}", quote(str(value), safe=""))
                path = re.sub(r"\{" + re.escape(p["name"]) + r":[^}]*\}", quote(str(value), safe=""), path)
            elif p["in"] == "query":
                query[p["name"]] = json.dumps(value) if isinstance(value, (dict, list)) else value
            elif spec["whole_body"]:
                body = value
            else:
                body = {**(body or {}), p["name"]: value}
        if spec["method"] not in READS and body is None and not spec["whole_body"] and any(
                p["in"] == "body" for p in spec["params"]):
            body = {}
        future = asyncio.run_coroutine_threadsafe(call(self.app, spec["method"], path, query, body), loop)
        try:
            status, ctype, data = future.result(TIMEOUT)
        except Exception as exc:                          # noqa: BLE001 - reported to the agent
            return _envelope_err("failed", f"{type(exc).__name__}: {exc}")
        text = data.decode("utf-8", "replace")
        result: Any = text[:RESULT_LIMIT]
        if "json" in ctype:
            try:
                result = json.loads(text)
            except ValueError:
                pass
        if status >= 400:
            detail = result.get("detail", result) if isinstance(result, dict) else result
            return _envelope_err("failed", f"HTTP {status}: {str(detail)[:2000]}")
        if isinstance(result, str) and len(text) > RESULT_LIMIT:
            result += " ...(cut)"
        return _envelope_ok(result)


async def call(app, method: str, path: str, query: dict | None = None, body: Any = None) -> tuple[int, str, bytes]:
    """One request through the app's own ASGI stack, in this process."""
    payload = b"" if body is None else json.dumps(body).encode("utf-8")
    headers = [(b"host", b"127.0.0.1"), (b"x-aiify-agent", b"1"), (b"content-length", str(len(payload)).encode())]
    if body is not None:
        headers.append((b"content-type", b"application/json"))
    scope = {"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": method,
             "scheme": "http", "path": path, "raw_path": path.encode(), "root_path": "",
             "query_string": urlencode(query or {}).encode(), "headers": headers,
             "client": ("127.0.0.1", 0), "server": ("127.0.0.1", 80)}
    sent = False
    done = asyncio.Event()
    status, ctype, chunks = 500, "", []

    async def receive():
        nonlocal sent
        if not sent:
            sent = True
            return {"type": "http.request", "body": payload, "more_body": False}
        await done.wait()
        return {"type": "http.disconnect"}

    async def send(message):
        nonlocal status, ctype
        if message["type"] == "http.response.start":
            status = message["status"]
            ctype = dict((k.lower(), v) for k, v in message.get("headers", [])).get(b"content-type", b"").decode()
        elif message["type"] == "http.response.body":
            chunks.append(message.get("body", b""))
            if not message.get("more_body"):
                done.set()

    await app(scope, receive, send)
    done.set()
    return status, ctype, b"".join(chunks)
