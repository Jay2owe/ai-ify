"""Level 1: run the app's own actions inside the live process.

An :class:`ActionSource` wraps whatever registry an app already has:

* :func:`from_dispatch` - apps exposing ``dispatch(action, params, root)`` and
  ``describe(action=None)`` (CircadianWorkbench ``actions.py``; ara
  ``control.py``, which also takes ``confirm``/``dry_run``);
* :func:`from_registry` - a ``{name: spec}`` mapping read by duck typing
  (``summary``, ``fn``, ``mutates``, ``destructive``, ``params``), the shape of
  analysis-kit's and ara's ``ActionSpec`` - neither is imported;
* :func:`from_functions` - plain callables for small apps.

:class:`ActionHost` adds the profile's :class:`~aiify.policy.Policy` and the
approval hook, and registers ``action.list`` / ``action.describe`` /
``action.run`` on the control port.
"""
from __future__ import annotations

import asyncio
import inspect
from fnmatch import fnmatchcase
from typing import Any, Awaitable, Callable, Iterable, Protocol

from .policy import Policy
from .protocol import AiifyError, Reply, serialize

AskUser = Callable[[str, dict, dict], Awaitable[bool]]


class ActionSource(Protocol):
    def names(self) -> list[str]: ...
    def describe(self, name: str | None = None) -> dict: ...
    def run(self, name: str, params: dict, *, confirm: bool = False) -> dict: ...


def _envelope_ok(result: Any, **extra) -> dict:
    return {"ok": True, "result": serialize(result), **serialize(extra)}


def _envelope_err(code: str, message: str, **extra) -> dict:
    return {"ok": False, "code": code, "error": message, **serialize(extra)}


def _accepts(fn: Callable, name: str) -> bool:
    try:
        sig = inspect.signature(fn)
    except (TypeError, ValueError):
        return False
    return name in sig.parameters or any(p.kind is p.VAR_KEYWORD for p in sig.parameters.values())


# -- apps with dispatch()/describe() ---------------------------------------------

class DispatchSource:
    """Wraps ``dispatch(action, params, root)``; replies are mapped onto ai-ify codes.

    App replies understood: ``{"ok": true, "result": ...}``; failures with
    ``needs_confirmation`` (CircadianWorkbench) or ``requires_confirmation``
    (ara); ``error_type``/``code`` of ``unknown_action``.
    """

    def __init__(self, dispatch: Callable, describe: Callable | None = None, *, root=None,
                 keep: Iterable[str] = ("equivalent_script",)):
        self._dispatch = dispatch
        self._describe = describe
        self.root = root
        self.keep = tuple(keep)
        self._takes_confirm = _accepts(dispatch, "confirm")
        self._cache: dict[str, dict] | None = None

    def _catalog(self) -> dict[str, dict]:
        if self._cache is None:
            cat: dict[str, dict] = {}
            if self._describe is not None:
                out = self._describe()
                rows = out.get("actions") if isinstance(out, dict) else out
                if isinstance(rows, dict):                       # ara: {name: {summary, ...}}
                    rows = [{"name": k, **v} for k, v in rows.items()]
                for row in rows or []:
                    if isinstance(row, dict) and row.get("name"):
                        cat[row["name"]] = {"name": row["name"], "summary": row.get("summary", ""),
                                            "mutates": bool(row.get("mutates")),
                                            "destructive": bool(row.get("destructive"))}
            self._cache = cat
        return self._cache

    def names(self) -> list[str]:
        return sorted(self._catalog())

    def describe(self, name: str | None = None) -> dict:
        if name is None:
            return {"actions": list(self._catalog().values())}
        if self._describe is not None:
            try:
                out = self._describe(name)
            except TypeError:
                out = None
            if isinstance(out, dict) and out.get("ok", True) is not False:
                out = {k: v for k, v in out.items() if k != "ok"}
                out.setdefault("name", name)
                return serialize(out)
        if name in self._catalog():
            return self._catalog()[name]
        raise AiifyError("unknown_action", f"unknown action {name!r}")

    def run(self, name: str, params: dict, *, confirm: bool = False) -> dict:
        params = dict(params or {})
        kwargs = {}
        if confirm:
            if self._takes_confirm:                      # ara: dispatch(..., confirm=True)
                kwargs["confirm"] = True
            elif "confirm" in self._param_names(name):   # CircadianWorkbench: a confirm parameter
                params.setdefault("confirm", True)
        try:
            reply = self._dispatch(name, params, self.root, **kwargs)
        except Exception as exc:                          # dispatch should never raise; guard anyway
            return _envelope_err("failed", f"{type(exc).__name__}: {exc}")
        if not isinstance(reply, dict):
            return _envelope_ok(reply)
        extra = {k: reply[k] for k in self.keep if k in reply}
        if reply.get("ok"):
            return _envelope_ok(reply.get("result"), **extra)
        if reply.get("needs_confirmation") or reply.get("requires_confirmation"):
            details = {k: v for k, v in reply.items()
                       if k not in ("ok", "error", "error_type", "code", "needs_confirmation",
                                    "requires_confirmation", "root", "action")}
            return _envelope_err("requires_confirmation", str(reply.get("error") or "needs confirmation"),
                                 requires_confirmation=True, details=details)
        kind = reply.get("error_type") or reply.get("code")
        code = "unknown_action" if kind == "unknown_action" else "failed"
        message = reply.get("error")
        if isinstance(message, dict):
            message = message.get("message") or str(message)
        return _envelope_err(code, str(message or kind or "action failed"), **extra)

    def _param_names(self, name: str) -> set[str]:
        try:
            info = self.describe(name)
        except AiifyError:
            return set()
        params = info.get("params") or info.get("parameters") or []
        if isinstance(params, dict):
            return set(params)
        return {p.get("name") for p in params if isinstance(p, dict)}


def from_dispatch(dispatch: Callable, describe: Callable | None = None, *, root=None) -> DispatchSource:
    return DispatchSource(dispatch, describe, root=root)


# -- {name: spec} registries -------------------------------------------------------

class RegistrySource:
    def __init__(self, mapping: dict, *, context_factory: Callable[[], Any] | None = None,
                 resolve: Callable[[str], Callable | None] | None = None):
        self.mapping = mapping
        self.context_factory = context_factory
        self.resolve = resolve

    def names(self) -> list[str]:
        return sorted(self.mapping)

    def _spec(self, name: str):
        if name not in self.mapping:
            raise AiifyError("unknown_action", f"unknown action {name!r}")
        return self.mapping[name]

    def _fn(self, spec) -> Callable | None:
        fn = getattr(spec, "fn", None)
        if fn is None and getattr(spec, "method", None) and self.resolve:
            fn = self.resolve(spec.method)
        return fn

    def describe(self, name: str | None = None) -> dict:
        if name is None:
            return {"actions": [self._row(n, self.mapping[n]) for n in self.names()]}
        spec = self._spec(name)
        row = self._row(name, spec)
        row["params"] = self._params(spec)
        return row

    @staticmethod
    def _row(name, spec) -> dict:
        return {"name": name, "summary": getattr(spec, "summary", "") or "",
                "mutates": bool(getattr(spec, "mutates", False)),
                "destructive": bool(getattr(spec, "destructive", False))}

    def _params(self, spec) -> list[dict]:
        declared = getattr(spec, "params", None)
        fn = self._fn(spec)
        sig = None
        if fn is not None:
            try:
                sig = inspect.signature(fn)
            except (TypeError, ValueError):
                sig = None
        if declared:
            return [{"name": p, "required": bool(sig and p in sig.parameters
                                                 and sig.parameters[p].default is inspect.Parameter.empty)}
                    for p in declared]
        out = []
        if sig is not None:
            for i, (pname, p) in enumerate(sig.parameters.items()):
                if i == 0 and pname in ("ctx", "context"):
                    continue
                if p.kind in (p.VAR_POSITIONAL, p.VAR_KEYWORD):
                    continue
                row = {"name": pname, "required": p.default is inspect.Parameter.empty}
                if not row["required"]:
                    row["default"] = serialize(p.default)
                out.append(row)
        return out

    def run(self, name: str, params: dict, *, confirm: bool = False) -> dict:
        try:
            spec = self._spec(name)
        except AiifyError as exc:
            return _envelope_err(exc.code, exc.message)
        fn = self._fn(spec)
        if fn is None:
            return _envelope_err("failed", f"action {name!r} has no function")
        params = dict(params or {})
        coerce = getattr(spec, "coerce", None) or {}
        try:
            params = {k: (coerce[k](v) if k in coerce else v) for k, v in params.items()}
            if confirm and _accepts(fn, "confirm"):
                params.setdefault("confirm", True)
            args = []
            first = next(iter(inspect.signature(fn).parameters), None)
            if first in ("ctx", "context"):
                args.append(self.context_factory() if self.context_factory else None)
            return _envelope_ok(fn(*args, **params))
        except AiifyError as exc:
            return _envelope_err(exc.code, exc.message, **exc.extra)
        except Exception as exc:
            if type(exc).__name__ in ("ConfirmationRequired", "ActionConfirmationRequired"):
                return _envelope_err("requires_confirmation", str(exc), requires_confirmation=True,
                                     details=serialize(getattr(exc, "payload", None) or {}))
            return _envelope_err("failed", f"{type(exc).__name__}: {exc}")


def from_registry(mapping: dict, *, context_factory=None, resolve=None) -> RegistrySource:
    return RegistrySource(mapping, context_factory=context_factory, resolve=resolve)


# -- plain functions ------------------------------------------------------------

class _FnSpec:
    def __init__(self, fn, *, summary, mutates, destructive):
        self.fn = fn
        self.summary = summary
        self.mutates = mutates
        self.destructive = destructive
        self.params = None


def from_functions(funcs: dict[str, Callable], *, destructive: Iterable[str] = (),
                   mutating: Iterable[str] = ()) -> RegistrySource:
    destructive, mutating = set(destructive), set(mutating)
    mapping = {}
    for name, fn in funcs.items():
        doc = (inspect.getdoc(fn) or "").strip().splitlines()
        mapping[name] = _FnSpec(fn, summary=doc[0] if doc else "",
                                mutates=name in mutating or name in destructive,
                                destructive=name in destructive)
    return RegistrySource(mapping)


class CombinedSource:
    """Several sources as one: the app's own registry plus integration extras.
    The first source that has a name answers for it."""

    def __init__(self, sources: Iterable[Any]):
        self.sources = [as_source(s) for s in sources]

    def _owner(self, name: str):
        return next((s for s in self.sources if name in s.names()), None)

    def names(self) -> list[str]:
        seen: list[str] = []
        for s in self.sources:
            seen += [n for n in s.names() if n not in seen]
        return seen

    def describe(self, name: str | None = None) -> dict:
        if name is None:
            rows, seen = [], set()
            for s in self.sources:
                for row in s.describe().get("actions", []):
                    if row.get("name") not in seen:
                        seen.add(row.get("name"))
                        rows.append(row)
            return {"ok": True, "actions": rows}
        owner = self._owner(name)
        return owner.describe(name) if owner else _envelope_err("unknown_action", f"unknown action {name!r}")

    def run(self, name: str, params: dict, *, confirm: bool = False) -> dict:
        owner = self._owner(name)
        if owner is None:
            return _envelope_err("unknown_action", f"unknown action {name!r}")
        return owner.run(name, params, confirm=confirm)


def combine(*sources: Any) -> CombinedSource:
    return CombinedSource(sources)


def as_source(obj: Any) -> ActionSource:
    """Accept an ActionSource, a {name: spec} mapping, or a module/object with
    ``dispatch`` + ``describe``."""
    if obj is None:
        return from_functions({})
    if all(hasattr(obj, a) for a in ("names", "describe", "run")):
        return obj
    if isinstance(obj, dict):
        if obj and all(callable(v) for v in obj.values()):
            return from_functions(obj)
        return from_registry(obj)
    if callable(getattr(obj, "dispatch", None)):
        return from_dispatch(obj.dispatch, getattr(obj, "describe", None))
    raise TypeError(f"cannot use {type(obj).__name__} as an action source")


# -- policy + approval + control-port ops ------------------------------------------

class ActionHost:
    """The source, the current profile's policy and the approval hook."""

    def __init__(self, source: Any, policy: Policy | None = None, *, ask_user: AskUser | None = None):
        self.source = as_source(source)
        self.policy = policy or Policy()
        self.ask_user = ask_user

    def summaries(self, match: str | None = None) -> list[dict]:
        rows = sorted(self.source.describe().get("actions", []), key=lambda r: r["name"])
        return [r for r in rows if self.policy.visible(r["name"])
                and (not match or fnmatchcase(r["name"], match))]

    def _spec(self, name: str) -> dict:
        for row in self.source.describe().get("actions", []):
            if row.get("name") == name:
                return row
        raise AiifyError("unknown_action", f"unknown action {name!r}; use action.list")

    async def run(self, name: str, params: dict | None = None, *, confirm: bool = False) -> dict:
        if not isinstance(name, str) or not name:
            raise AiifyError("invalid", "action.run needs a name")
        if params is not None and not isinstance(params, dict):
            raise AiifyError("invalid", "params must be a JSON object")
        params = params or {}
        spec = self._spec(name)
        decision = self.policy.check(name, spec)
        if decision == "deny":
            raise AiifyError("denied", f"{name} is not allowed for this profile")
        if decision == "confirm" and not confirm:
            confirm = await self._approve(name, params, spec)
        reply = await asyncio.to_thread(self.source.run, name, params, confirm=confirm)
        if not reply.get("ok") and reply.get("code") == "requires_confirmation" and not confirm:
            # The app asked for confirmation itself (not marked destructive in its registry).
            if await self._approve(name, params, {**spec, **(reply.get("details") or {})}):
                reply = await asyncio.to_thread(self.source.run, name, params, confirm=True)
        return reply

    async def _approve(self, name: str, params: dict, spec: dict) -> bool:
        if self.ask_user is not None:
            try:
                approved = await self.ask_user(name, params, spec)
            except AiifyError:
                approved = None
            if approved is True:
                return True
            if approved is False:
                raise AiifyError("denied", f"the person declined {name}")
        raise AiifyError("requires_confirmation",
                         f"{name} needs the person's approval: ask them, then repeat with confirm=true",
                         requires_confirmation=True)

    # control-port handlers -----------------------------------------------------
    def register(self, port) -> None:
        port.register("action.list", self._op_list)
        port.register("action.describe", self._op_describe)
        port.register("action.run", self._op_run)
        port.describer("actions", lambda: {"count": len(self.summaries()),
                                           "hint": "action.list for names, action.describe NAME for parameters"})

    async def _op_list(self, req: dict):
        match = req.get("match")
        if match is not None and not isinstance(match, str):
            raise AiifyError("invalid", "match must be a string")
        return await asyncio.to_thread(self.summaries, match)

    async def _op_describe(self, req: dict):
        name = req.get("name")
        if not isinstance(name, str):
            raise AiifyError("invalid", "action.describe needs a name")
        if not self.policy.visible(name):
            raise AiifyError("denied", f"{name} is not allowed for this profile")
        return await asyncio.to_thread(self.source.describe, name)

    async def _op_run(self, req: dict):
        confirm = req.get("confirm", False)
        if type(confirm) is not bool:
            raise AiifyError("invalid", "confirm must be true or false")
        reply = await self.run(req.get("name"), req.get("params"), confirm=confirm)
        if not reply.get("ok"):
            extra = {k: v for k, v in reply.items() if k not in ("ok", "code", "error", "result")}
            raise AiifyError(reply.get("code", "failed"), reply.get("error", "action failed"), **extra)
        extra = {k: v for k, v in reply.items() if k not in ("ok", "result")}
        return Reply(reply.get("result"), extra)
