"""Hooks, suggested prompts, locked pickers, one-off questions, attachments, app
notes, and queued / scheduled messages."""
import functools
import sys
import time
from datetime import timedelta
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel

from aiify import AgentReply, Agent, Answer, Launch, Profile
from aiify.protocol import AiifyError

FAKE = [sys.executable, str(Path(__file__).with_name("fake_acp_agent.py"))]
H = {"X-Aiify": "1"}


@pytest.fixture(autouse=True)
def fake_store(tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_ACP_STORE", str(tmp_path / "sessions.json"))


def make(**kw):
    agent = Agent("cfgtest", engine_argv={"claude": FAKE}, limit_check_every=None, **kw)
    app = FastAPI()
    agent.mount(app)
    return app, agent


def until(ws, kind, limit=400, where=lambda ev: True):
    seen = []
    for _ in range(limit):
        ev = ws.receive_json()
        seen.append(ev)
        if ev.get("kind") == kind and where(ev):
            return ev, seen
    raise AssertionError(f"no {kind} event in {[e.get('kind') for e in seen]}")


def texts(events):
    return "".join(e["text"] for e in events if e.get("kind") == "text")


def post(client, route, **body):
    return client.post("/aiify/api/" + route, json=body, headers=H)


def test_before_send_can_answer_rewrite_or_hold_back():
    seen = []

    def before(turn):
        seen.append(turn.text)
        if "price" in turn.text:
            return Answer("It costs 40 pounds.")
        if "rewrite" in turn.text:
            return "echo REWRITTEN"
        if "boom" in turn.text:
            raise RuntimeError("checker down")
        return None

    app, agent = make(before_send=before)
    with TestClient(app) as client, client.websocket_connect("/aiify/ws") as ws:
        ws.receive_json()
        post(client, "send", text="what is the price")
        done, events = until(ws, "done")
        assert texts(events) == "It costs 40 pounds." and done["by_app"]
        post(client, "send", text="rewrite this")
        _, events = until(ws, "done")
        assert [e["text"] for e in events if e["kind"] == "user"] == ["rewrite this"]   # the chat shows what was typed
        assert "[Message from the person]\nREWRITTEN" not in texts(events)
        assert "echo REWRITTEN" in texts(events)
        post(client, "send", text="boom")
        done, events = until(ws, "done")
        assert done["stop"] == "refused"
        assert any(e["kind"] == "error" and "checker down" in e["text"] for e in events)
        assert seen == ["what is the price", "rewrite this", "boom"]


def test_after_reply_gets_the_reply():
    got = []

    async def after(turn, reply: AgentReply):
        got.append((turn.text, reply.text, reply.stop, reply.tools))

    app, agent = make(after_reply=after)
    with TestClient(app) as client, client.websocket_connect("/aiify/ws") as ws:
        ws.receive_json()
        post(client, "send", text="hi")
        until(ws, "done")
        for _ in range(50):
            if got:
                break
            time.sleep(0.02)
        assert got == [("hi", "hello from fake", "end_turn", 1)]


def test_suggestions_in_an_empty_chat_and_per_launch():
    app, agent = make(suggestions=lambda turn: [f"Explain {turn.state['view']}", {"label": "Short", "text": "echo short"}],
                      state=lambda: {"view": "plots"},
                      launches={"fig": Launch(label="Figure", suggestions=["What does the red line show?"])})
    with TestClient(app) as client, client.websocket_connect("/aiify/ws") as ws:
        hello = ws.receive_json()
        assert hello["info"]["suggestions"] == [{"label": "Explain plots", "text": "Explain plots"},
                                                {"label": "Short", "text": "echo short"}]
        post(client, "send", text="hi")
        until(ws, "done")
        assert agent.info()["suggestions"] == []           # gone once the chat has started
        post(client, "launch", name="fig")
        assert agent.info()["suggestions"] == [{"label": "What does the red line show?",
                                                "text": "What does the red line show?"}]


def test_locked_and_limited_pickers():
    app, agent = make(profiles={"main": Profile(lock=["model"], limit={"effort": ["low", "high"]}),
                                "other": Profile()})
    with TestClient(app) as client, client.websocket_connect("/aiify/ws") as ws:
        ws.receive_json()
        post(client, "send", text="hi")
        until(ws, "done")
        info = agent.info()
        assert info["locked"] == ["model"]
        assert info["options"]["effort"]["value"] == "low"          # moved off "default" into the limit
        assert info["options"]["effort"]["choices"] == ["low", "high"]
        r = post(client, "settings", model="smart").json()
        assert not r["ok"] and r["code"] == "denied"
        r = post(client, "settings", effort="default").json()
        assert not r["ok"] and r["code"] == "denied"
        assert post(client, "settings", effort="high").json()["ok"]
        client.portal.call(functools.partial(agent.configure, model="smart"))   # the app itself may
        assert agent.info()["options"]["model"]["value"] == "smart"
    with pytest.raises(ValueError, match="unknown picker"):
        Profile(lock=["colour"])


def test_ask_from_the_apps_code():
    class Count(BaseModel):
        n: int

    app, agent = make()
    with TestClient(app) as client:
        assert client.portal.call(functools.partial(agent.ask, "say hi", context=False)) == "hello from fake"
        got = client.portal.call(functools.partial(agent.ask, 'reply-json {"n": 3}', context=False,
                                                   schema={"type": "object", "required": ["n"]}))
        assert got == {"n": 3}
        got = client.portal.call(functools.partial(agent.ask, 'reply-json {"n": 4}', context=False, schema=Count))
        assert got == Count(n=4)
        got = client.portal.call(functools.partial(agent.ask, "reply-bad", context=False,
                                                   schema={"type": "object"}))
        assert got == {"fixed": True}                      # asked again once
        assert agent.session is None                       # the chat was not touched


def test_attachments_go_with_the_next_message(tmp_path):
    app, agent = make(attachments=True)
    with TestClient(app) as client, client.websocket_connect("/aiify/ws") as ws:
        ws.receive_json()
        a = post(client, "attach", name="notes.txt", text="line one\nline two").json()
        b = post(client, "attach", name="dot.png", data_url="data:image/png;base64,iVBORw0KGgo=").json()
        assert a["ok"] and b["ok"]
        assert [x["name"] for x in agent.info()["attachments"]] == ["notes.txt", "dot.png"]
        post(client, "send", text="echo look")
        _, events = until(ws, "done")
        sent = texts(events)
        assert "[Attached]" in sent and "notes.txt" in sent and "    line two" in sent and "dot.png" in sent
        png = next(Path(line.split(": ", 1)[1].rsplit(" (", 1)[0]) for line in sent.splitlines() if "dot.png:" in line)
        assert png.read_bytes() == b"\x89PNG\r\n\x1a\n"
        assert agent.info()["attachments"] == []
        r = post(client, "launch", name="nope", attach=[{"name": "a", "text": "b"}])
        assert r.status_code == 400


def test_page_attach_never_reads_server_files(tmp_path):
    secret = tmp_path / "secret.txt"
    secret.write_text("secret")
    app, agent = make()
    with TestClient(app) as client:
        r = post(client, "attach", name="s", path=str(secret)).json()
        assert not r["ok"]                                 # neither text nor data_url given
        assert agent.info()["attachments"] == []


def test_app_notes_across_chats(tmp_path):
    notes_file = tmp_path / "notes.md"
    app, agent = make(notes=notes_file)
    with TestClient(app) as client, client.websocket_connect("/aiify/ws") as ws:
        ws.receive_json()
        reply = client.portal.call(agent.port.handlers["notes.add"], {"text": "Prefers  SEM error bars"})
        assert reply["added"].endswith("Prefers SEM error bars")
        post(client, "send", text="echo hi")
        _, events = until(ws, "done")
        assert "[App notes]" in texts(events) and "Prefers SEM error bars" in texts(events)
        assert "notes.add" in texts(events)
        post(client, "send", text="echo again")
        _, events = until(ws, "done")
        assert "[App notes]" not in texts(events)          # once per chat
    assert "Prefers SEM error bars" in notes_file.read_text(encoding="utf-8")


def test_queue_sends_after_the_reply_and_stop_hands_it_back():
    app, agent = make(queue=True)
    with TestClient(app) as client, client.websocket_connect("/aiify/ws") as ws:
        ws.receive_json()
        assert post(client, "queue", text="echo first").json()["queued"] is False   # idle: sent at once
        until(ws, "done")
        post(client, "send", text="slow")
        until(ws, "text")
        r = post(client, "queue", text="echo second").json()
        assert r["queued"] and agent.info()["pending"][0]["text"] == "echo second"
        post(client, "cancel")
        ev, _ = until(ws, "unqueued")
        assert ev["texts"] == ["echo second"] and agent.info()["pending"] == []
        until(ws, "done")
        post(client, "send", text="slow")
        until(ws, "text")
        post(client, "queue", text="echo third")
        until(ws, "done")                                  # the slow one ends by itself
        _, events = until(ws, "done")
        assert [e["text"] for e in events if e["kind"] == "user"] == ["echo third"]


def test_schedule_sends_at_the_time():
    app, agent = make(schedule=True)
    with TestClient(app) as client, client.websocket_connect("/aiify/ws") as ws:
        ws.receive_json()
        r = post(client, "schedule", text="echo later", at="2001-01-01T00:00:00Z").json()
        assert not r["ok"] and "passed" in r["error"]
        kept = client.portal.call(agent.schedule_message, "echo dropped", timedelta(hours=1))
        client.portal.call(agent.schedule_message, "echo later", timedelta(seconds=0.5))
        assert [p["text"] for p in agent.info()["pending"]] == ["echo later", "echo dropped"]
        assert post(client, "unqueue", id=kept["id"]).json()["removed"]
        ev, _ = until(ws, "user")
        assert ev["text"] == "echo later"
        until(ws, "done")
        assert agent.info()["pending"] == []


def test_queue_and_schedule_routes_need_the_app_to_turn_them_on():
    app, agent = make()
    with TestClient(app) as client:
        assert post(client, "queue", text="x").json()["code"] == "not_supported"
        assert post(client, "schedule", text="x", at="2099-01-01T00:00:00Z").json()["code"] == "not_supported"
        with pytest.raises(AiifyError):
            client.portal.call(agent.schedule_message, "x", "not a time")
