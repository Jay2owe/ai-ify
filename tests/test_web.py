"""The FastAPI mount, websocket flow and approvals, with the scripted fake agent."""
import concurrent.futures
import contextlib
import io
import json
import shutil
import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from aiify import Agent, Profile, When
from aiify import console as console_mod
from aiify.actions import from_functions
from aiify.cli import main as cli_main
from aiify.control_port import list_apps

FAKE = [sys.executable, str(Path(__file__).with_name("fake_acp_agent.py"))]
H = {"X-Aiify": "1"}


@pytest.fixture(autouse=True)
def fake_store(tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_ACP_STORE", str(tmp_path / "sessions.json"))


def make_app(**kw):
    removed = []

    def wipe():
        """Delete everything."""
        removed.append(1)
        return "wiped"

    def look():
        """Look around."""
        return "nothing here"

    agent = Agent("webtest", actions=from_functions({"wipe": wipe, "look": look}, destructive=["wipe"]),
                  profiles={"main": Profile(instructions="MAIN-INSTR"),
                            "viewer": Profile(allow=["look"], label="Viewer")},
                  state=lambda: {"view": "plots"},
                  rules=[When(lambda s: s["view"] == "plots", "RULE-PLOTS")],
                  engine_argv={"claude": FAKE, "codex": FAKE}, **kw)
    app = FastAPI()
    agent.mount(app)
    return app, agent, removed


def until(ws, kind, limit=200):
    seen = []
    for _ in range(limit):
        ev = ws.receive_json()
        seen.append(ev)
        if ev.get("kind") == kind:
            return ev, seen
    raise AssertionError(f"no {kind} event in {[e.get('kind') for e in seen]}")


def texts(events):
    return "".join(e["text"] for e in events if e.get("kind") == "text")


def test_static_files_and_guard():
    app, agent, _ = make_app()
    with TestClient(app) as client:
        r = client.get("/aiify/panel.js")
        assert r.status_code == 200 and "window.aiify" in r.text
        assert client.get("/aiify/panel.css").status_code == 200
        assert client.get("/aiify/../agent.py").status_code == 404
        assert client.get("/aiify/nothing.js").status_code == 404
        assert client.post("/aiify/api/new", json={}).status_code == 403          # no header
        assert client.post("/aiify/api/new", json={}, headers={**H, "Origin": "http://evil.example"}).status_code == 403
        info = client.get("/aiify/api/info").json()
        assert info["app"] == "webtest" and info["profile"] == "main"
        assert [p["name"] for p in info["profiles"]] == ["main", "viewer"]
        assert info["console"]["available"] is False


def test_port_registered_for_the_apps_lifetime():
    app, agent, _ = make_app()
    with TestClient(app):
        assert [a["app"] for a in list_apps()] == ["webtest"]
    assert list_apps() == []


def test_chat_streams_over_the_websocket():
    app, agent, _ = make_app()
    with TestClient(app) as client, client.websocket_connect("/aiify/ws") as ws:
        hello = ws.receive_json()
        assert hello["kind"] == "hello" and hello["history"] == []
        until(ws, "ready")
        assert client.post("/aiify/api/send", json={"text": "echo hi there"}, headers=H).json()["ok"]
        done, seen = until(ws, "done")
        first = next(e for e in seen if e["kind"] != "info")
        assert first["kind"] == "user" and first["text"] == "echo hi there"
        sent = texts(seen)
        assert "MAIN-INSTR" in sent and "RULE-PLOTS" in sent and '"view":"plots"' in sent
        assert sent.rstrip().endswith("echo hi there") and done["stop"] == "end_turn"
        # second message: no orientation again
        client.post("/aiify/api/send", json={"text": "echo again"}, headers=H)
        _, seen = until(ws, "done")
        assert "MAIN-INSTR" not in texts(seen) and "RULE-PLOTS" in texts(seen)
        # a panel opened later gets the conversation so far
        with client.websocket_connect("/aiify/ws") as ws2:
            late = ws2.receive_json()
            assert [e["kind"] for e in late["history"]].count("user") == 2


def test_permission_card_answered_from_the_panel():
    app, agent, _ = make_app()
    with TestClient(app) as client, client.websocket_connect("/aiify/ws") as ws:
        ws.receive_json()
        client.post("/aiify/api/send", json={"text": "permission"}, headers=H)
        perm, _ = until(ws, "permission")
        assert perm["title"] == "delete things" and [o["id"] for o in perm["options"]] == ["yes", "no"]
        assert client.post("/aiify/api/answer", json={"id": perm["id"], "option": "no"}, headers=H).json()["answered"]
        _, seen = until(ws, "done")
        assert texts(seen) == "outcome=no"


def test_stop_cancels_a_running_message():
    app, agent, _ = make_app()
    with TestClient(app) as client, client.websocket_connect("/aiify/ws") as ws:
        ws.receive_json()
        client.post("/aiify/api/send", json={"text": "slow"}, headers=H)
        until(ws, "text")
        assert client.post("/aiify/api/send", json={"text": "again"}, headers=H).status_code == 400   # busy
        client.post("/aiify/api/cancel", json={}, headers=H)
        done, _ = until(ws, "done", limit=400)
        assert done["stop"] == "cancelled"


def test_action_approval_card_and_policy(monkeypatch):
    app, agent, removed = make_app()
    with TestClient(app) as client, client.websocket_connect("/aiify/ws") as ws:
        ws.receive_json()
        with concurrent.futures.ThreadPoolExecutor(1) as pool:
            def run_cli(*argv):
                buf = io.StringIO()
                code = cli_main(["--app", "webtest", *argv], out=buf)
                return code, json.loads(buf.getvalue())

            job = pool.submit(run_cli, "action.run", "wipe")
            card, _ = until(ws, "permission")
            assert card["source"] == "action" and card["title"] == "Run wipe?"
            client.post("/aiify/api/answer", json={"id": card["id"], "option": "yes"}, headers=H)
            code, out = job.result(30)
            assert code == 0 and out["result"] == "wiped" and removed == [1]

            job = pool.submit(run_cli, "action.run", "wipe")
            card, _ = until(ws, "permission")
            client.post("/aiify/api/answer", json={"id": card["id"], "option": "no"}, headers=H)
            code, out = job.result(30)
            assert out["code"] == "denied" and removed == [1]

        # the viewer profile cannot see or run wipe
        info = client.post("/aiify/api/settings", json={"profile": "viewer"}, headers=H).json()["info"]
        assert info["profile"] == "viewer"
        buf = io.StringIO()
        cli_main(["--app", "webtest", "action.list"], out=buf)
        assert [r["name"] for r in json.loads(buf.getvalue())["result"]] == ["look"]


def test_action_without_panel_returns_requires_confirmation():
    app, agent, removed = make_app()
    with TestClient(app):
        buf = io.StringIO()
        code = cli_main(["--app", "webtest", "action.run", "wipe"], out=buf)
        assert code == 1 and json.loads(buf.getvalue())["code"] == "requires_confirmation"
        assert removed == []


def test_settings_new_chat_and_console(monkeypatch):
    real_which = shutil.which
    monkeypatch.setattr(console_mod.shutil, "which",
                        lambda n, *a, **k: f"C:/fake/{n}.exe" if n in ("claude", "codex") else real_which(n, *a, **k))
    launched = []
    monkeypatch.setattr(console_mod, "launch", lambda argv, cwd: launched.append((argv, cwd)))
    # CI Linux machines have no terminal emulator; the wrapper is covered elsewhere
    monkeypatch.setattr(console_mod, "terminal_argv", lambda cwd, argv, **kw: ["term"] + list(argv))
    app, agent, _ = make_app()
    with TestClient(app) as client, client.websocket_connect("/aiify/ws") as ws:
        ws.receive_json()
        until(ws, "ready")
        info = client.post("/aiify/api/settings", json={"model": "smart", "effort": "high"}, headers=H).json()["info"]
        assert info["options"]["model"]["value"] == "smart" and info["options"]["effort"]["value"] == "high"
        r = client.post("/aiify/api/settings", json={"model": "nonsense"}, headers=H)
        assert r.status_code == 400
        assert info["console"]["available"] is True
        sid = info["session"]
        r = client.post("/aiify/api/console", json={}, headers=H).json()
        assert r["ok"] and launched and launched[0][0][-3:] == ["C:/fake/claude.exe", "--resume", sid]
        # the next message reopens the same conversation (the console may have added to it)
        client.post("/aiify/api/send", json={"text": "history"}, headers=H)
        _, seen = until(ws, "done")
        assert agent.session.session_id == sid and texts(seen) == "turns=1"
        # provider switch starts a new chat
        client.post("/aiify/api/settings", json={"provider": "codex"}, headers=H)
        until(ws, "reset")
        assert agent.provider == "codex" and agent.history[-1]["kind"] in ("reset", "status", "ready")
        client.post("/aiify/api/new", json={}, headers=H)
        until(ws, "reset")


def test_mount_keeps_the_apps_own_lifespan():
    events = []

    @contextlib.asynccontextmanager
    async def own(app):
        events.append("app up")
        yield
        events.append("app down")

    app = FastAPI(lifespan=own)
    agent = Agent("lifetest", engine_argv={"claude": FAKE})
    agent.mount(app)
    with TestClient(app):
        assert events == ["app up"] and agent.started
    assert events == ["app up", "app down"] and not agent.started


def test_auto_allow_only_the_apps_own_plain_command():
    agent = Agent("CW")
    opts = [{"id": "a", "kind": "allow_once"}, {"id": "r", "kind": "reject_once"}]
    ask = lambda c: agent._auto_answer({"command": c, "options": opts})
    assert ask('"C:\\Py\\python.exe" -m aiify --app CW action.list') == "a"
    assert ask("aiify --app CW state") == "a"
    assert ask(r"& C:\Py\python.exe -m aiify --app CW action.list") == "a"     # PowerShell form
    assert ask(r"& C:\Py\python.exe -m aiify --app CW state & del x") is None
    assert ask('"C:\\Py\\python.exe" -m aiify --app CW state && del x') is None
    assert ask('"C:\\Py\\python.exe" -m aiify --app Other state') is None
    assert ask("rm -rf /") is None
    assert ask("") is None


def test_auto_allow_chained_own_commands_only():
    agent = Agent("aiify-demo")
    opts = [{"id": "a", "kind": "allow_once"}]
    ask = lambda c: agent._auto_answer({"command": c, "options": opts})
    py = r"D:\tools\venv\Scripts\python.exe"
    one = f"& {py} -m aiify --app aiify-demo"
    assert ask(f"{one} action.describe samples.add; {one} action.describe view.show") == "a"
    assert ask(f"""{one} action.run samples.add 'name="M;04"' 'genotype="APP"'""") == "a"
    assert ask(f"{one} state && {one} describe") == "a"
    assert ask(f"{one} state; del secrets.txt") is None
    assert ask(f"{one} state | Out-File x") is None
    assert ask(f'{one} action.run x "v=$(whoami)"') is None
    assert ask(f"C:/evil.exe -m aiify --app aiify-demo state") is None
    assert ask(f"{one}-other state") is None
    assert ask(f"{one} action.run samples.remove sample_id=1 --confirm") is None   # skips the card
    assert ask(f"""{one} raw '{{"op": "action.run", "confirm": true}}'""") is None
    assert ask(f"{one} action.run samples.add confirm=true") == "a"             # just a parameter
