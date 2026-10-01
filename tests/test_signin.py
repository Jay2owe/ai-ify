"""Signing in from the panel, with the fake agent playing a signed-out Claude or Codex."""
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from aiify import Agent, Profile
from aiify import agent as agent_mod
from aiify import console as console_mod
from aiify import engine as engine_mod
from aiify.engine import AcpSession

FAKE = [sys.executable, str(Path(__file__).with_name("fake_acp_agent.py"))]
H = {"X-Aiify": "1"}


@pytest.fixture
def signed_out(tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_ACP_STORE", str(tmp_path / "sessions.json"))
    marker = tmp_path / "signed-in"
    monkeypatch.setenv("FAKE_ACP_SIGNIN", str(marker))
    monkeypatch.setattr(agent_mod, "SIGNIN_POLL", 0.1)
    return marker


def make_app(provider: str):
    agent = Agent("signintest", profiles={"main": Profile(provider=provider)},
                  engine_argv={provider: FAKE}, limit_check_every=None)
    app = FastAPI()
    agent.mount(app)
    return app, agent


def until(ws, kind, limit=300):
    seen = []
    for _ in range(limit):
        ev = ws.receive_json()
        seen.append(ev)
        if ev.get("kind") == kind:
            return ev, seen
    raise AssertionError(f"no {kind} event in {[e.get('kind') for e in seen]}")


def test_claude_style_terminal_signin_resends_the_message(signed_out, monkeypatch):
    monkeypatch.setenv("FAKE_ACP_SIGNIN_AT", "prompt")
    windows = []

    def finish_in_the_window(argv, cwd, **kw):       # the person signs in in the new window
        windows.append(argv)
        subprocess.run(argv, check=True)
        return argv

    monkeypatch.setattr(console_mod, "open_window", finish_in_the_window)
    app, agent = make_app("claude")
    with TestClient(app) as client, client.websocket_connect("/aiify/ws") as ws:
        ws.receive_json()
        until(ws, "ready")                             # Claude opens the chat while signed out
        client.post("/aiify/api/send", json={"text": "echo hello there"}, headers=H)
        need, _ = until(ws, "auth_required")
        assert [m["id"] for m in need["methods"]] == ["claude-ai-login"]   # no API-key or ChatGPT routes
        done, _ = until(ws, "done")
        assert done["stop"] == "auth_required"
        assert agent.info()["signin"]["methods"][0]["type"] == "terminal"

        r = client.post("/aiify/api/signin", json={}, headers=H).json()
        assert r["ok"] and r["waiting"] == "claude-ai-login"
        assert windows[0][-3:] == ["--cli", "auth", "login"]
        _, seen = until(ws, "done")                    # the watcher saw the sign-in; the message went again
        kinds = [e["kind"] for e in seen]
        assert "signed_in" in kinds and "user" not in kinds    # not shown twice
        reply = "".join(e["text"] for e in seen if e["kind"] == "text")
        assert reply.rstrip().endswith("echo hello there") and "signintest" in reply   # orientation included
        assert agent.info()["signin"] is None and signed_out.exists()


def test_codex_style_agent_signin_opens_the_chat(signed_out, monkeypatch):
    monkeypatch.setenv("FAKE_ACP_SIGNIN_AT", "session")
    app, agent = make_app("codex")
    with TestClient(app) as client, client.websocket_connect("/aiify/ws") as ws:
        ws.receive_json()
        need, _ = until(ws, "auth_required")           # Codex cannot open a chat at all
        assert [m["id"] for m in need["methods"]] == ["chat-gpt"]
        assert agent.info()["ready"] is False
        client.post("/aiify/api/send", json={"text": "echo after signing in"}, headers=H)
        done, _ = until(ws, "done")
        assert done["stop"] == "auth_required"

        assert client.post("/aiify/api/signin", json={"method": "nope"}, headers=H).status_code == 400
        assert client.post("/aiify/api/signin", json={"method": "chat-gpt"}, headers=H).json()["ok"]
        _, seen = until(ws, "done")
        kinds = [e["kind"] for e in seen]
        assert kinds.index("ready") < kinds.index("signed_in")
        assert "echo after signing in" in "".join(e["text"] for e in seen if e["kind"] == "text")
        assert agent.info()["ready"] and agent.info()["signin"] is None
        assert client.post("/aiify/api/signin", json={"check": True}, headers=H).json()["signed_in"]


def test_signed_in_check_button_when_the_watcher_has_not_noticed(signed_out, monkeypatch):
    monkeypatch.setenv("FAKE_ACP_SIGNIN_AT", "prompt")
    monkeypatch.setattr(agent_mod, "SIGNIN_POLL", 60)  # the watcher stays asleep
    monkeypatch.setattr(console_mod, "open_window", lambda argv, cwd, **kw: argv)
    app, agent = make_app("claude")
    with TestClient(app) as client, client.websocket_connect("/aiify/ws") as ws:
        ws.receive_json()
        until(ws, "ready")
        client.post("/aiify/api/send", json={"text": "echo one"}, headers=H)
        until(ws, "done")
        client.post("/aiify/api/signin", json={}, headers=H)
        assert agent.info()["signin"]["waiting"] == "claude-ai-login"
        # "I've signed in" while still signed out: Claude's own check says no, the card stays
        r = client.post("/aiify/api/signin", json={"check": True}, headers=H).json()
        assert r["signed_in"] is False and agent.info()["signin"]["waiting"] == "claude-ai-login"
        signed_out.write_text("signed in")
        assert client.post("/aiify/api/signin", json={"check": True}, headers=H).json()["signed_in"]
        _, seen = until(ws, "done")
        assert "echo one" in "".join(e["text"] for e in seen if e["kind"] == "text")


def test_missing_node_says_how_to_fix_it(monkeypatch):
    monkeypatch.setattr(engine_mod.shutil, "which", lambda name, *a, **k: None)
    import asyncio

    async def go():
        s = AcpSession("claude", cwd=".")
        with pytest.raises(RuntimeError, match="nodejs.org"):
            await s.start()
    asyncio.run(go())


def test_console_falls_back_to_the_bundled_cli(monkeypatch):
    real = shutil.which
    monkeypatch.setattr(console_mod.shutil, "which",
                        lambda n, *a, **k: "C:/node/npx.cmd" if n == "npx" else None if n in ("claude", "codex")
                        else real(n, *a, **k))
    assert console_mod.vendor_argv("claude", "S1") == [
        "C:/node/npx.cmd", "-y", "@agentclientprotocol/claude-agent-acp", "--cli", "--resume", "S1"]
    assert console_mod.vendor_argv("codex", "S2") == [
        "C:/node/npx.cmd", "-y", "-p", "@agentclientprotocol/codex-acp", "codex", "resume", "S2"]
    monkeypatch.setattr(console_mod.shutil, "which", lambda n, *a, **k: None)
    with pytest.raises(FileNotFoundError, match="Node.js"):
        console_mod.vendor_argv("claude", "S1")
