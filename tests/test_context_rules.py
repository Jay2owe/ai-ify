"""Developer context: rules on what was typed, the settings and the launch; launches from buttons."""
import re
import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from aiify import Agent, Launch, Profile, Turn, When
from aiify.prompting import active_rules, build_message

FAKE = [sys.executable, str(Path(__file__).with_name("fake_acp_agent.py"))]
H = {"X-Aiify": "1"}


def test_prompt_conditions():
    word = When(prompt="cost", add_instructions="COST")
    assert word.matches(Turn(text="What will this Cost?")) and word.matches(Turn(text="costs and fees"))
    assert not word.matches(Turn(text="accost")) and not word.matches(Turn(text="price"))
    assert When(prompt=["price", "fee"], add_instructions="x").matches(Turn(text="the fee"))
    assert When(prompt=re.compile(r"\bp\d+\b"), add_instructions="x").matches(Turn(text="see p12"))
    assert When(prompt=lambda t: len(t) > 5, add_instructions="x").matches(Turn(text="longer"))
    assert not When(prompt=lambda t: 1 / 0, add_instructions="x").matches(Turn(text="boom"))


def test_setting_and_launch_conditions():
    deep = When(model="opus*", effort=["high", "xhigh"], add_instructions="DEEP")
    assert deep.matches(Turn(model="opus-4", effort="high"))
    assert not deep.matches(Turn(model="sonnet", effort="high"))
    assert not deep.matches(Turn(model=None, effort="high"))          # unknown model: no match
    assert When(provider="codex", add_instructions="x").matches(Turn(provider="codex"))
    assert When(profile="analyst", launch="explain-*", add_instructions="x").matches(
        Turn(profile="analyst", launch="explain-figure"))
    assert When(lambda s: s["view"] == "plots", "x").matches({"view": "plots"})     # state alone still works
    assert When(add_instructions="always").matches(Turn())


def test_context_functions_get_the_turn_and_failures_are_reported():
    seen = []
    rules = [When(prompt="cost", add_instructions=lambda turn: seen.append(turn) or f"Budget {turn.state['budget']}"),
             When(add_instructions=lambda turn: None),                       # adds nothing
             When(add_instructions=lambda turn: {}["missing"], name="broken")]
    notes = active_rules(rules, Turn(text="the cost?", state={"budget": 40}))
    assert notes[0] == "Budget 40" and seen[0].text == "the cost?"
    assert notes[1].startswith("(the app's rule broken could not be built: KeyError")
    assert len(notes) == 2


def test_launch_context_in_the_message():
    launch = Launch(label="Explain this figure", instructions=lambda t: f"Figure {t.data['figure']} shows rhythms.",
                    rules=[When(add_instructions="LAUNCH-RULE")])
    turn = Turn(text="hi", data={"figure": "fig2"}, launch="explain")
    first = build_message("hi", app="a", profile=Profile(), first=True, turn=turn, launch=launch, launch_new=True)
    assert 'started this with "Explain this figure"' in first and "Figure fig2 shows rhythms." in first
    assert '[Started with] {"figure":"fig2"}' in first and "LAUNCH-RULE" in first
    later = build_message("more", app="a", profile=Profile(), first=False, turn=turn, launch=launch)
    assert "Figure fig2" not in later and "LAUNCH-RULE" in later           # rules stay for the chat
    mid = build_message("x", app="a", profile=Profile(), first=False, turn=turn, launch=launch, launch_new=True)
    assert mid.startswith("[The person started a new request from the app]")


@pytest.fixture(autouse=True)
def fake_store(tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_ACP_STORE", str(tmp_path / "sessions.json"))


def until(ws, kind, limit=300):
    seen = []
    for _ in range(limit):
        ev = ws.receive_json()
        seen.append(ev)
        if ev.get("kind") == kind:
            return ev, seen
    raise AssertionError(f"no {kind} event in {[e.get('kind') for e in seen]}")


def texts(events):
    return "".join(e["text"] for e in events if e.get("kind") == "text")


def make():
    prices = []

    def price_note(turn):
        prices.append(turn.text)
        return "Say the plan costs 40 pounds a month."

    agent = Agent(
        "ctxtest", engine_argv={"claude": FAKE}, limit_check_every=None,
        profiles={"main": Profile(), "analyst": Profile(instructions="ANALYST-PROFILE", effort="high")},
        rules=[When(prompt="cost", add_instructions=price_note),
               When(effort="high", add_instructions="EFFORT-HIGH-RULE")],
        launches={"explain": Launch(label="Explain this figure", profile="analyst",
                                    instructions=lambda t: f"FIGURE-{t.data['figure']}",
                                    message=lambda t: f"echo explain {t.data['figure']}"),
                  "ask": Launch(label="Ask about samples", message="", new_chat=False,
                                instructions="SAMPLES-CONTEXT")})
    app = FastAPI()
    agent.mount(app)
    return app, agent, prices


def test_prompt_trigger_calls_the_apps_function():
    app, agent, prices = make()
    with TestClient(app) as client, client.websocket_connect("/aiify/ws") as ws:
        ws.receive_json()
        client.post("/aiify/api/send", json={"text": "echo what does it cost"}, headers=H)
        _, seen = until(ws, "done")
        assert "Say the plan costs 40 pounds a month." in texts(seen) and prices == ["echo what does it cost"]
        client.post("/aiify/api/send", json={"text": "echo hello"}, headers=H)
        _, seen = until(ws, "done")
        assert "40 pounds" not in texts(seen) and len(prices) == 1


def test_a_launch_button_starts_its_own_chat():
    app, agent, _ = make()
    with TestClient(app) as client, client.websocket_connect("/aiify/ws") as ws:
        ws.receive_json()
        r = client.post("/aiify/api/launch", json={"name": "explain", "data": {"figure": "fig2"}}, headers=H).json()
        assert r["ok"] and r["sent"]
        _, seen = until(ws, "done")
        sent = texts(seen)
        assert "FIGURE-fig2" in sent and "ANALYST-PROFILE" in sent and '"figure":"fig2"' in sent
        assert "EFFORT-HIGH-RULE" in sent                 # the launch's profile set effort=high
        assert sent.rstrip().endswith("echo explain fig2")
        info = agent.info()
        assert info["profile"] == "analyst" and info["launch"] == {"name": "explain", "label": "Explain this figure"}
        assert [l["name"] for l in info["launches"]] == ["explain", "ask"]
        client.post("/aiify/api/send", json={"text": "echo next"}, headers=H)
        _, seen = until(ws, "done")
        assert "FIGURE-fig2" not in texts(seen)            # told once
        client.post("/aiify/api/new", json={}, headers=H)
        until(ws, "reset")
        assert agent.info()["launch"] is None
        assert client.post("/aiify/api/launch", json={"name": "nope"}, headers=H).status_code == 400


def test_a_launch_can_join_the_current_chat():
    app, agent, _ = make()
    with TestClient(app) as client, client.websocket_connect("/aiify/ws") as ws:
        ws.receive_json()
        client.post("/aiify/api/send", json={"text": "echo first"}, headers=H)
        _, seen = until(ws, "done")
        session = agent.session.session_id
        assert client.post("/aiify/api/launch", json={"name": "ask"}, headers=H).json()["sent"] is False
        client.post("/aiify/api/send", json={"text": "echo which samples"}, headers=H)
        _, seen = until(ws, "done")
        sent = texts(seen)
        assert agent.session.session_id == session          # same conversation
        assert "[The person started a new request from the app]" in sent and "SAMPLES-CONTEXT" in sent


def test_unknown_launch_profile_fails_at_start():
    with pytest.raises(ValueError, match="unknown profile"):
        Agent("bad", launches={"x": Launch(profile="nobody")})
