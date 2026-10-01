"""The control port <-> page relay, with a scripted page instead of a browser."""
import concurrent.futures
import io
import json
import sys
import threading
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from aiify import Agent
from aiify.actions import from_functions
from aiify.cli import main as cli_main
from aiify.ui_relay import UiRelay

FAKE = [sys.executable, str(Path(__file__).with_name("fake_acp_agent.py"))]


@pytest.fixture(autouse=True)
def fake_store(tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_ACP_STORE", str(tmp_path / "sessions.json"))


def cli(*argv):
    buf = io.StringIO()
    code = cli_main(["--app", "relaytest", *argv], out=buf)
    return code, json.loads(buf.getvalue())


def make(**kw):
    agent = Agent("relaytest", actions=from_functions({"look": lambda: "seen"}),
                  state=lambda: {"backend": 1}, engine_argv={"claude": FAKE}, **kw)
    agent.relay.timeout = kw.pop("timeout", 3)
    app = FastAPI()
    agent.mount(app)
    return app, agent


TOOLS = [{"name": "show_view", "description": "Switch view",
          "inputSchema": {"type": "object", "properties": {"view": {"enum": ["a", "b"]}}}}]


class ScriptedPage:
    """Answers ui.request messages the way bridge.js would."""

    def __init__(self, ws, answers):
        self.ws, self.answers, self.seen = ws, answers, []
        self.stop = threading.Event()

    def run(self):
        while not self.stop.is_set():
            try:
                ev = self.ws.receive_json()
            except Exception:
                return
            if ev.get("kind") != "ui.request":
                continue
            self.seen.append(ev)
            answer = self.answers.get(ev["op"])
            if answer == "silent":
                continue
            if answer is None:
                answer = {"ok": False, "code": "unknown_op", "error": "no"}
            self.ws.send_json({"type": "ui.reply", "id": ev["id"], **answer})


def test_no_ui_without_a_page_but_actions_work():
    app, agent = make()
    with TestClient(app):
        code, out = cli("ui", "tree")
        assert code == 1 and out["code"] == "no_ui"
        code, out = cli("action.run", "look")
        assert code == 0 and out["result"] == "seen"
        code, out = cli("state")
        assert out["result"] == {"backend": 1}
        code, out = cli("screenshot")
        assert out["code"] == "not_supported"
        code, out = cli("describe")
        assert out["result"]["ui_attached"] is False
        assert out["result"]["levels"]["ui_commands"]["attached"] is False


def test_requests_go_to_the_page_and_back():
    app, agent = make()
    answers = {
        "ui.tree": {"ok": True, "result": {"snapshot": 1, "elements": [{"ref": "e1", "role": "button", "label": "Go"}]}},
        "ui.click": {"ok": True, "result": {"clicked": "e1"}, "screen_changed": True},
        "ui.read": {"ok": False, "code": "stale_ref", "error": "ask again"},
        "ui.do": {"ok": True, "result": {"view": "b"}, "screen_changed": True},
        "ui.state": {"ok": True, "result": {"view": "b"}},
    }
    with TestClient(app) as client, client.websocket_connect("/aiify/ws") as ws:
        ws.receive_json()
        ws.send_json({"type": "bridge.hello", "tools": TOOLS, "url": "http://x/", "title": "Demo"})
        page = ScriptedPage(ws, answers)
        t = threading.Thread(target=page.run, daemon=True)
        t.start()
        try:
            code, out = cli("describe")
            ui = out["result"]["levels"]["ui_commands"]
            assert out["result"]["ui_attached"] and ui["commands"][0]["name"] == "show_view"
            code, out = cli("ui", "tree", "match=go")
            assert out["result"]["elements"][0]["ref"] == "e1"
            assert page.seen[-1]["match"] == "go"
            code, out = cli("ui", "click", "e1")
            assert out["result"] == {"clicked": "e1"} and out["screen_changed"] is True
            code, out = cli("ui", "read", "e1")
            assert code == 1 and out["code"] == "stale_ref"
            code, out = cli("ui", "do", "show_view", "view=b")
            assert out["result"] == {"view": "b"} and page.seen[-1]["params"] == {"view": "b"}
            code, out = cli("state")
            assert out["result"] == {"view": "b", "backend": 1}         # page state merged with backend
            code, out = cli("ui", "click")
            assert out["code"] == "invalid"                              # checked before reaching the page
        finally:
            page.stop.set()


def test_page_that_never_answers_times_out():
    app, agent = make()
    with TestClient(app) as client, client.websocket_connect("/aiify/ws") as ws:
        ws.receive_json()
        ws.send_json({"type": "bridge.hello", "tools": []})
        page = ScriptedPage(ws, {"ui.tree": "silent"})
        threading.Thread(target=page.run, daemon=True).start()
        agent.relay.timeout = 0.5
        code, out = cli("ui", "tree")
        assert out["code"] == "timeout"
        page.stop.set()


def test_closing_the_page_detaches_it():
    app, agent = make()
    with TestClient(app) as client:
        with client.websocket_connect("/aiify/ws") as ws:
            ws.receive_json()
            ws.send_json({"type": "bridge.hello", "tools": TOOLS})
            ws.send_json({"type": "bridge.tools", "tools": []})
            for _ in range(50):
                if agent.relay.attached:
                    break
                threading.Event().wait(0.02)
            assert agent.relay.attached
        for _ in range(100):
            if not agent.relay.attached:
                break
            threading.Event().wait(0.02)
        assert not agent.relay.attached
        assert cli("ui", "tree")[1]["code"] == "no_ui"


def test_relay_unit_drop_fails_waiting_requests():
    import asyncio

    async def go():
        relay = UiRelay(timeout=5)
        q = asyncio.Queue()
        relay.on_hello({"tools": []}, q)
        task = asyncio.ensure_future(relay.request("ui.tree"))
        await asyncio.sleep(0)
        assert (await q.get())["op"] == "ui.tree"
        relay.drop(q)
        with pytest.raises(Exception) as e:
            await task
        return e.value

    err = asyncio.run(go())
    assert getattr(err, "code", None) == "no_ui"
