import io
import json

import pytest

from aiify.cli import build_request, main
from aiify.control_port import ControlPort


def test_build_request_shapes():
    assert build_request(["ping"]) == {"op": "ping"}
    assert build_request(["ui", "tree"]) == {"op": "ui.tree"}
    assert build_request(["ui", "click", "e12"]) == {"op": "ui.click", "target": "e12"}
    assert build_request(["ui", "fill", "threshold", "0.4"]) == {"op": "ui.fill", "target": "threshold", "value": "0.4"}
    assert build_request(["ui", "do", "show_view", "view=plots"]) == {
        "op": "ui.do", "name": "show_view", "params": {"view": "plots"}}
    assert build_request(["action.run", "plot.bar", 'markers=["Iba1"]', "n=3"], confirm=True) == {
        "op": "action.run", "name": "plot.bar", "params": {"markers": ["Iba1"], "n": 3}, "confirm": True}
    assert build_request(["action", "list", "match=plot.*"]) == {"op": "action.list", "match": "plot.*"}
    assert build_request(["raw", '{"op": "state"}']) == {"op": "state"}
    with pytest.raises(ValueError):
        build_request(["ui"])
    with pytest.raises(ValueError):
        build_request(["ping", "extra"])


def _run(argv):
    buf = io.StringIO()
    code = main(argv, out=buf)
    return code, json.loads(buf.getvalue())


def test_cli_against_live_port(loop_thread):
    port = ControlPort("clitest")

    async def state(req):
        return {"view": "table", "asked": req.get("detail")}

    port.register("state", state)
    loop_thread.run(port.start())
    try:
        code, out = _run(["apps"])
        assert code == 0 and [a["app"] for a in out["result"]] == ["clitest"]
        code, out = _run(["ping"])
        assert code == 0 and out["result"]["app"] == "clitest"
        code, out = _run(["--app", "cli", "state", "detail=1"])
        assert code == 0 and out["result"] == {"view": "table", "asked": 1}
        code, out = _run(["--app", "other", "ping"])
        assert code == 1 and "no running app" in out["error"]
        code, out = _run(["nope"])
        assert code == 1 and out["code"] == "unknown_op"
    finally:
        loop_thread.run(port.stop())


def test_cli_without_apps():
    code, out = _run(["ping"])
    assert code == 1 and "no app" in out["error"]


def test_cli_two_apps_needs_name(loop_thread):
    a, b = ControlPort("one"), ControlPort("two")
    loop_thread.run(a.start())
    loop_thread.run(b.start())
    try:
        code, out = _run(["ping"])
        assert code == 1 and "--app" in out["error"]
        code, out = _run(["--app", "two", "ping"])
        assert code == 0 and out["result"]["app"] == "two"
    finally:
        loop_thread.run(a.stop())
        loop_thread.run(b.stop())
