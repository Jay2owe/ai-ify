"""Signing in from the panel, with the fake agent playing a signed-out Claude or Codex."""
import shutil
import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from aiify import Agent, Profile
from aiify import console as console_mod
from aiify import engine as engine_mod
from aiify.engine import AcpSession
from aiify.signin import find_link
from aiify.testing.fake_agent import LOGIN_LINK as FAKE_LINK

FAKE = [sys.executable, str(Path(__file__).with_name("fake_acp_agent.py"))]
H = {"X-Aiify": "1"}


@pytest.fixture
def signed_out(tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_ACP_STORE", str(tmp_path / "sessions.json"))
    marker = tmp_path / "signed-in"
    monkeypatch.setenv("FAKE_ACP_SIGNIN", str(marker))
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


def wait_for(predicate, timeout=20.0):
    import time
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if predicate():
            return
        time.sleep(0.05)
    raise AssertionError("timed out")


def test_claude_style_signin_in_the_panel_resends_the_message(signed_out, monkeypatch):
    monkeypatch.setenv("FAKE_ACP_SIGNIN_AT", "prompt")
    app, agent = make_app("claude")
    with TestClient(app) as client, client.websocket_connect("/aiify/ws") as ws:
        ws.receive_json()
        until(ws, "ready")                             # Claude opens the chat while signed out
        client.post("/aiify/api/send", json={"text": "echo hello there"}, headers=H)
        need, _ = until(ws, "auth_required")
        assert [m["id"] for m in need["methods"]] == ["claude-ai-login"]   # no API-key or ChatGPT routes
        done, _ = until(ws, "done")
        assert done["stop"] == "auth_required"

        r = client.post("/aiify/api/signin", json={}, headers=H).json()
        assert r["ok"] and r["waiting"] == "claude-ai-login"
        wait_for(lambda: agent.info()["signin"]["link"])           # the login runs with no window
        info = agent.info()["signin"]
        assert info["link"] == FAKE_LINK and info["code"] is True
        assert client.post("/aiify/api/signin", json={"code": "GOODCODE"}, headers=H).json()["sent"]
        _, seen = until(ws, "done")                    # signed in; the message went again
        kinds = [e["kind"] for e in seen]
        assert "signed_in" in kinds and "user" not in kinds    # not shown twice
        reply = "".join(e["text"] for e in seen if e["kind"] == "text")
        assert reply.rstrip().endswith("echo hello there") and "signintest" in reply   # orientation included
        assert agent.info()["signin"] is None and signed_out.exists()


def test_a_wrong_code_ends_that_attempt_and_sign_in_can_start_again(signed_out, monkeypatch):
    monkeypatch.setenv("FAKE_ACP_SIGNIN_AT", "prompt")
    app, agent = make_app("claude")
    with TestClient(app) as client, client.websocket_connect("/aiify/ws") as ws:
        ws.receive_json()
        until(ws, "ready")
        client.post("/aiify/api/send", json={"text": "echo one"}, headers=H)
        until(ws, "done")
        assert client.post("/aiify/api/signin", json={"code": "x"}, headers=H).status_code == 400   # none running
        client.post("/aiify/api/signin", json={}, headers=H)
        wait_for(lambda: agent.info()["signin"]["link"])
        client.post("/aiify/api/signin", json={"code": "WRONG"}, headers=H)
        err, _ = until(ws, "error")
        assert "did not finish" in err["text"]
        assert agent.info()["signin"]["waiting"] is None and not signed_out.exists()
        client.post("/aiify/api/signin", json={}, headers=H)
        wait_for(lambda: agent.info()["signin"]["link"])
        client.post("/aiify/api/signin", json={"code": "GOODCODE"}, headers=H)
        _, seen = until(ws, "done")
        assert "echo one" in "".join(e["text"] for e in seen if e["kind"] == "text")


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
        assert client.post("/aiify/api/signin", json={}, headers=H).json()["error"] == "already signed in"


def test_the_link_is_read_from_claudes_real_login_output():
    text = (Path(__file__).parent / "fixtures" / "claude_login.txt").read_text(encoding="utf-8")
    link = find_link(text)
    assert link.startswith("https://claude.com/cai/oauth/authorize?code=true&") and link.endswith("state=STATE")
    assert find_link(text[:120]) is None               # not until the whole link has arrived


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
