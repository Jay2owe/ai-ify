"""Adapters against registries shaped like the lab's apps (shapes copied, nothing imported)."""
import asyncio
import json
from dataclasses import dataclass, field
from typing import Any, Callable

import pytest

from aiify.actions import ActionHost, as_source, from_dispatch, from_functions, from_registry
from aiify.control_port import ControlPort
from aiify.policy import Policy
from aiify.protocol import AiifyError


# -- a CircadianWorkbench-shaped dispatch/describe -----------------------------------

CW_STATE = {"files": ["a.csv", "b.csv"], "calls": []}


def cw_dispatch(action, params=None, root=None):
    params = params or {}
    CW_STATE["calls"].append((action, dict(params)))
    if action == "list_output":
        return {"ok": True, "action": action, "result": {"count": len(CW_STATE["files"])},
                "equivalent_script": "dispatch('list_output')", "provenance": {"big": "x" * 10}}
    if action == "clear_output":
        if not params.get("confirm"):
            return {"ok": False, "action": action, "error_type": "needs_confirmation",
                    "needs_confirmation": True, "error": "clear_output requires confirm=true.",
                    "would_remove": 2, "root": "r", "equivalent_script": "..."}
        CW_STATE["files"].clear()
        return {"ok": True, "action": action, "result": {"removed": 2}}
    if action == "nan_result":
        return {"ok": True, "result": {"x": float("inf")}}
    return {"ok": False, "action": action, "error_type": "unknown_action", "error": f"Unknown action: {action!r}."}


def cw_describe(action=None):
    rows = [
        {"name": "list_output", "summary": "List output files", "mutates": False, "destructive": False,
         "params": []},
        {"name": "clear_output", "summary": "Delete the output folder", "mutates": True, "destructive": True,
         "params": [{"name": "confirm", "type": "bool", "required": False, "default": False}]},
        {"name": "nan_result", "summary": "Returns infinity", "mutates": False, "destructive": False, "params": []},
    ]
    if action is None:
        return {"ok": True, "actions": rows}
    for r in rows:
        if r["name"] == action:
            return {"ok": True, **r}
    return {"ok": False, "error_type": "unknown_action", "error": "nope"}


@pytest.fixture(autouse=True)
def reset_cw():
    CW_STATE["files"][:] = ["a.csv", "b.csv"]
    CW_STATE["calls"].clear()


def run(coro):
    return asyncio.run(coro)


def test_dispatch_source_maps_cw_replies():
    src = from_dispatch(cw_dispatch, cw_describe)
    assert src.names() == ["clear_output", "list_output", "nan_result"]
    r = src.run("list_output", {})
    assert r["ok"] and r["result"] == {"count": 2} and r["equivalent_script"]
    assert "provenance" not in r                         # big fields are not passed through
    r = src.run("clear_output", {})
    assert r["code"] == "requires_confirmation" and r["details"]["would_remove"] == 2
    r = src.run("clear_output", {}, confirm=True)
    assert r["ok"] and r["result"] == {"removed": 2}
    assert CW_STATE["calls"][-1] == ("clear_output", {"confirm": True})
    assert src.run("missing", {})["code"] == "unknown_action"
    assert json.dumps(src.run("nan_result", {}), allow_nan=False)


def test_host_destructive_without_ui_requires_confirmation():
    host = ActionHost(from_dispatch(cw_dispatch, cw_describe))
    with pytest.raises(AiifyError) as e:
        run(host.run("clear_output", {}))
    assert e.value.code == "requires_confirmation"
    assert CW_STATE["files"] == ["a.csv", "b.csv"]          # nothing ran
    r = run(host.run("clear_output", {}, confirm=True))
    assert r["ok"] and CW_STATE["files"] == []


def test_host_asks_the_person_when_a_ui_is_attached():
    asked = []

    async def yes(name, params, spec):
        asked.append(name)
        return True

    host = ActionHost(from_dispatch(cw_dispatch, cw_describe), ask_user=yes)
    r = run(host.run("clear_output"))
    assert r["ok"] and asked == ["clear_output"]

    async def no(name, params, spec):
        return False

    host.ask_user = no
    with pytest.raises(AiifyError) as e:
        run(host.run("clear_output"))
    assert e.value.code == "denied"


def test_policy_denies_and_hides():
    host = ActionHost(from_dispatch(cw_dispatch, cw_describe), Policy.from_lists(allow=["list_*"]))
    assert [r["name"] for r in host.summaries()] == ["list_output"]
    with pytest.raises(AiifyError) as e:
        run(host.run("nan_result"))
    assert e.value.code == "denied"


# -- an agentify-shaped {name: ActionSpec} registry ---------------------------

class ConfirmationRequired(Exception):          # the analysis-kit class, by name only
    def __init__(self, message, payload=None):
        super().__init__(message)
        self.payload = payload or {}


@dataclass(frozen=True)
class ActionSpec:
    summary: str
    fn: Callable
    mutates: bool = False
    destructive: bool = False
    coerce: dict = field(default_factory=dict)
    params: Any = None


def add_task(ctx, title: str, priority: int = 1):
    return {"title": title, "priority": priority, "root": ctx["root"]}


def drop_all(ctx, confirm: bool = False):
    if not confirm:
        raise ConfirmationRequired("drop_all needs confirm", {"would_drop": 3})
    return {"dropped": 3}


REGISTRY = {
    "task.add": ActionSpec("Add a task", add_task, mutates=True, coerce={"priority": int}),
    "task.drop_all": ActionSpec("Drop every task", drop_all, mutates=True),   # not flagged destructive
}


def test_registry_source_with_context_and_coercion():
    src = from_registry(REGISTRY, context_factory=lambda: {"root": "/tmp/x"})
    r = src.run("task.add", {"title": "t", "priority": "3"})
    assert r["ok"] and r["result"] == {"title": "t", "priority": 3, "root": "/tmp/x"}
    params = src.describe("task.add")["params"]
    assert params[0] == {"name": "title", "required": True}
    assert params[1]["name"] == "priority" and params[1]["default"] == 1


def test_app_raised_confirmation_goes_through_approval():
    src = from_registry(REGISTRY, context_factory=lambda: {"root": "r"})
    assert src.run("task.drop_all", {})["code"] == "requires_confirmation"
    seen = []

    async def yes(name, params, spec):
        seen.append(spec.get("would_drop"))
        return True

    host = ActionHost(src, ask_user=yes)
    r = run(host.run("task.drop_all"))
    assert r["ok"] and r["result"] == {"dropped": 3} and seen == [3]


def test_from_functions_and_as_source():
    def hello(name: str = "world"):
        """Say hello."""
        return f"hello {name}"

    def wipe():
        return "wiped"

    src = from_functions({"hello": hello, "wipe": wipe}, destructive=["wipe"])
    rows = {r["name"]: r for r in src.describe()["actions"]}
    assert rows["hello"]["summary"] == "Say hello." and rows["wipe"]["destructive"]
    assert src.run("hello", {"name": "x"})["result"] == "hello x"
    assert as_source({"hello": hello}).run("hello", {})["result"] == "hello world"
    assert as_source(REGISTRY).names() == ["task.add", "task.drop_all"]


def test_control_port_ops(loop_thread):
    from aiify.cli import main
    import io

    host = ActionHost(from_dispatch(cw_dispatch, cw_describe))
    port = ControlPort("acts")
    host.register(port)
    loop_thread.run(port.start())
    try:
        def cli(*argv):
            buf = io.StringIO()
            code = main(list(argv), out=buf)
            return code, json.loads(buf.getvalue())

        code, out = cli("action.list")
        assert code == 0 and [r["name"] for r in out["result"]] == ["clear_output", "list_output", "nan_result"]
        code, out = cli("action", "list", "match=list_*")
        assert [r["name"] for r in out["result"]] == ["list_output"]
        code, out = cli("action.describe", "clear_output")
        assert out["result"]["destructive"] is True
        code, out = cli("action.run", "clear_output")
        assert code == 1 and out["code"] == "requires_confirmation" and out["requires_confirmation"]
        code, out = cli("action.run", "clear_output", "--confirm")
        assert code == 0 and out["result"] == {"removed": 2}
        code, out = cli("action.run", "nope")
        assert out["code"] == "unknown_action"
        code, out = cli("action.run", "list_output")
        assert out["equivalent_script"] == "dispatch('list_output')"
        code, out = cli("describe")
        assert out["result"]["levels"]["actions"]["count"] == 3
    finally:
        loop_thread.run(port.stop())


def test_combine_sources():
    from aiify.actions import combine

    def extra():
        """An integration extra."""
        return "extra"

    src = combine(from_dispatch(cw_dispatch, cw_describe), from_functions({"app.extra": extra}))
    assert src.names() == ["list_output", "clear_output", "nan_result", "app.extra"] or \
        sorted(src.names()) == ["app.extra", "clear_output", "list_output", "nan_result"]
    assert [r["name"] for r in src.describe()["actions"]][-1] == "app.extra"
    assert src.run("app.extra", {})["result"] == "extra"
    assert src.run("list_output", {})["result"] == {"count": 2}
    assert src.run("nope", {})["code"] == "unknown_action"
    host = ActionHost(src)
    assert "app.extra" in [r["name"] for r in host.summaries()]
