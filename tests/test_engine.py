"""AcpSession against the scripted fake agent - no npx, Claude or Codex is started."""
import asyncio
import json
import sys
from pathlib import Path

import pytest

from aiify import engine
from aiify.control_port import pid_alive
from aiify.engine import AcpSession, child_env

FAKE = [sys.executable, str(Path(__file__).with_name("fake_acp_agent.py"))]


@pytest.fixture
def spawned(monkeypatch, tmp_path):
    """Record every process the engine starts, and give the fake agent its own store."""
    seen = []
    real = engine.acp.spawn_agent_process

    def spy(client, exe, *args, **kw):
        seen.append([Path(exe).name.lower(), *[Path(a).name.lower() for a in args]])
        return real(client, exe, *args, **kw)

    monkeypatch.setattr(engine.acp, "spawn_agent_process", spy)
    monkeypatch.setenv("FAKE_ACP_STORE", str(tmp_path / "sessions.json"))
    yield seen
    assert seen, "nothing was started"
    for argv in seen:
        assert argv[0].startswith("python") and argv[1] == "fake_acp_agent.py", argv


def make(tmp_path, events, handler=None, **kw):
    return AcpSession("claude", cwd=tmp_path, on_event=events.append, permission_handler=handler,
                      argv=FAKE, **kw)


def texts(events):
    return "".join(e["text"] for e in events if e["kind"] == "text")


def test_start_options_stream_and_close(spawned, tmp_path):
    events = []

    async def go():
        s = make(tmp_path, events)
        await s.start()
        assert s.options() == {"model": {"value": "fast", "choices": ["fast", "smart"]},
                               "effort": {"value": "default", "choices": ["default", "low", "high"]},
                               "mode": {"value": "default", "choices": ["default", "plan"]}}
        await s.set_option("model", "smart")
        assert s.options()["model"]["value"] == "smart"
        with pytest.raises(ValueError):
            await s.set_option("model", "nope")
        summary = await s.send("hi")
        pid = s.pid
        assert pid and pid_alive(pid)
        await s.close()
        return summary, pid

    summary, pid = asyncio.run(go())
    assert summary["stop"] == "end_turn" and summary["tools"] == 1
    assert summary["first_words"] is not None
    kinds = [e["kind"] for e in events]
    assert kinds[0] == "status" and "ready" in kinds and kinds[-1] == "done"
    assert texts(events) == "hello from fake"
    tool = next(e for e in events if e["kind"] == "tool")
    assert tool["title"] == "list files" and tool["detail"] == "dir"
    assert any(e["kind"] == "tool_update" and e["status"] == "completed" and "a.csv" in e["detail"]
               for e in events)
    usage = next(e for e in events if e["kind"] == "usage")["usage"]
    assert usage["_meta"]["_claude/rateLimit"]["utilization"] == 0.2     # kept for usage bars
    assert not pid_alive(pid)                                            # no orphan left


def test_settings_applied_at_start(spawned, tmp_path):
    async def go():
        s = make(tmp_path, [], settings={"model": "smart", "effort": "high", "mode": None})
        await s.start()
        opts = s.options()
        await s.close()
        return opts

    opts = asyncio.run(go())
    assert opts["model"]["value"] == "smart" and opts["effort"]["value"] == "high"


@pytest.mark.parametrize("choice,expected", [("yes", "outcome=yes"), (None, "outcome=cancelled")])
def test_permission_allowed_and_denied(spawned, tmp_path, choice, expected):
    events, asked = [], []

    async def handler(req):
        asked.append(req)
        return choice

    async def go():
        s = make(tmp_path, events, handler)
        await s.start()
        await s.send("permission please")
        await s.close()

    asyncio.run(go())
    assert asked[0]["title"] == "delete things" and asked[0]["detail"] == "rm -rf stuff"
    assert [o["id"] for o in asked[0]["options"]] == ["yes", "no"]
    done = next(e for e in events if e["kind"] == "permission_done")
    assert done["option"] == choice
    assert texts(events) == expected


def test_no_handler_refuses(spawned, tmp_path):
    events = []

    async def go():
        s = make(tmp_path, events)
        await s.start()
        await s.send("permission")
        await s.close()

    asyncio.run(go())
    assert texts(events) == "outcome=cancelled"


def test_cancel_mid_message(spawned, tmp_path):
    events = []

    async def go():
        s = make(tmp_path, events)
        await s.start()
        turn = asyncio.create_task(s.send("slow"))
        while not any(e["kind"] == "text" for e in events):
            await asyncio.sleep(0.02)
        await s.cancel()
        summary = await asyncio.wait_for(turn, 10)
        await s.close()
        return summary

    summary = asyncio.run(go())
    assert summary["stop"] == "cancelled"
    assert sum(e["kind"] == "text" for e in events) < 200


@pytest.mark.parametrize("caps", ["resume,load", "load"])
def test_resume_a_closed_session(spawned, tmp_path, monkeypatch, caps):
    monkeypatch.setenv("FAKE_ACP_CAPS", caps)

    async def go():
        first = make(tmp_path, [])
        await first.start()
        await first.set_option("effort", "low")
        await first.send("history")
        sid = first.session_id
        await first.close()

        events = []
        again = make(tmp_path, events, session_id=sid)
        await again.start()
        assert again.can_resume and again.session_id == sid
        assert again.options()["effort"]["value"] == "low"
        await again.send("history")
        await again.close()
        return events

    assert texts(asyncio.run(go())) == "turns=2"


def test_unknown_session_starts_a_new_one(spawned, tmp_path):
    events = []

    async def go():
        s = make(tmp_path, events, session_id="missing")
        await s.start()
        sid = s.session_id
        await s.close()
        return sid

    assert asyncio.run(go()) != "missing"
    assert any(e["kind"] == "status" and "could not reopen" in e["text"] for e in events)


def test_no_resume_when_not_advertised(spawned, tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_ACP_CAPS", "")

    async def go():
        s = make(tmp_path, [])
        await s.start()
        can = s.can_resume
        await s.close()
        return can

    assert asyncio.run(go()) is False


def test_child_env_is_scrubbed(monkeypatch):
    monkeypatch.setenv("CLAUDECODE", "1")
    monkeypatch.setenv("AC_THING", "x")
    monkeypatch.setenv("KEEP_ME", "y")
    env = child_env({"EXTRA": "z"})
    assert "CLAUDECODE" not in env and "AC_THING" not in env
    assert env["KEEP_ME"] == "y" and env["EXTRA"] == "z"


def test_unknown_provider_rejected(tmp_path):
    with pytest.raises(ValueError):
        AcpSession("gemini", cwd=tmp_path)


def test_start_failure_is_reported(tmp_path):
    events = []

    async def go():
        s = AcpSession("claude", cwd=tmp_path, on_event=events.append,
                       argv=[sys.executable, "-c", "import sys; sys.exit(3)"])
        with pytest.raises(RuntimeError):
            await s.start()

    asyncio.run(go())
    assert any(e["kind"] == "error" for e in events)


def test_engine_command_override(monkeypatch, tmp_path):
    monkeypatch.setenv("FAKE_ACP_STORE", str(tmp_path / "s.json"))
    monkeypatch.setenv("AIIFY_ENGINE_COMMAND", json.dumps([sys.executable, "-m", "aiify.testing.fake_agent"]))
    events = []

    async def go():
        s = AcpSession("codex", cwd=tmp_path, on_event=events.append)
        assert s.argv[1:] == ["-m", "aiify.testing.fake_agent"]
        await s.start()
        await s.send("history")
        await s.close()

    asyncio.run(go())
    assert texts(events) == "turns=1"
    monkeypatch.setenv("AIIFY_ENGINE_COMMAND", "not json")
    with pytest.raises(ValueError):
        AcpSession("claude", cwd=tmp_path)
