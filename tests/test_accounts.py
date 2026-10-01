"""Codex account switching: only between messages, and only the active account is queried."""
import asyncio
import sys
from pathlib import Path

import pytest

from aiify import Agent, Profile
from aiify.accounts import CodexAccounts, ProfileError, parse_usage
from aiify.protocol import AiifyError

FAKE = [sys.executable, str(Path(__file__).with_name("fake_acp_agent.py"))]
STATUS = {"usage": {"state": "ok", "buckets": [
    {"id": "codex", "five_hour": {"left_percent": 70, "reset_at": 1791090000},
     "weekly": {"left_percent": 20, "reset_at": 1791122376}},
    {"id": "codex_bengalfox", "five_hour": {"left_percent": 99, "reset_at": 1791090000}}]}}


class FakeProfiles:
    """Stands in for codex-profiles; records every call."""

    def __init__(self):
        self.calls = []
        self.current = "a"

    def __call__(self, *args):
        self.calls.append(args)
        if args[0] == "list":
            return {"profiles": [{"id": i, "label": f"Account {i}", "is_current": i == self.current}
                                 for i in ("a", "b")]}
        if args[0] == "load":
            self.current = args[2]
            return {"command": "load", "success": True}
        if args[0] == "status":
            return STATUS
        raise ProfileError("unexpected")


@pytest.fixture(autouse=True)
def fake_store(tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_ACP_STORE", str(tmp_path / "sessions.json"))


def test_parse_usage_main_bucket_only():
    windows = parse_usage(STATUS, 1.0)
    assert {w.kind: round(w.used, 2) for w in windows} == {"five_hour": 0.3, "seven_day": 0.8}
    assert parse_usage({"usage": {"state": "error"}}, 1.0) == []
    assert parse_usage({"usage": {"state": "ok", "buckets": [
        {"id": "codex", "five_hour": {"left_percent": "nan"}}]}}, 1.0) == []


def test_switch_verifies_and_never_queries_by_id():
    fake = FakeProfiles()
    acc = CodexAccounts(run=fake)
    assert acc.refresh()["current"] == "a"
    assert acc.switch("b")["name"] == "Account b"
    assert acc.current == "b"
    acc.usage()
    with pytest.raises(ProfileError):
        acc.switch("bad id; rm")
    with pytest.raises(ProfileError):
        acc.switch("zzz")
    # usage is only ever asked of the active account
    assert [c for c in fake.calls if c[0] == "status"] == [("status",)]
    assert all("--all" not in c for c in fake.calls)


def test_switch_requested_mid_message_waits_for_it_to_end(tmp_path):
    fake = FakeProfiles()
    agent = Agent("acctest", profiles={"c": Profile(provider="codex")}, engine_argv={"codex": FAKE},
                  codex_accounts=CodexAccounts(run=fake), cwd=tmp_path / "work")
    events = []

    async def go():
        await agent.start()
        q = agent.subscribe()
        await asyncio.sleep(0.2)                     # the start-up account read
        info = agent.info()
        assert info["accounts"]["current"] == "a" and len(info["accounts"]["choices"]) == 2
        turn = asyncio.ensure_future(agent.send("slow"))
        while not agent.busy or not any(e["kind"] == "text" for e in events):
            while not q.empty():
                events.append(q.get_nowait())
            await asyncio.sleep(0.05)
        assert await agent.request_account("b") == {"pending": True}
        assert agent.info()["accounts"]["pending"] == "b"
        assert not [c for c in fake.calls if c[0] == "load"]        # nothing switched yet
        await asyncio.sleep(0.3)
        assert not [c for c in fake.calls if c[0] == "load"]
        await agent.cancel()
        await asyncio.wait_for(turn, 15)
        assert [c for c in fake.calls if c[0] == "load"] == [("load", "--id", "b")]
        info = agent.info()
        assert info["accounts"]["current"] == "b" and info["accounts"]["pending"] is None
        assert {w["kind"] for w in info["limits"]["providers"]["codex"]} == {"five_hour", "seven_day"}
        assert agent._stale                            # Codex restarts signed in as b
        assert (await agent.request_account("a"))["account"]["id"] == "a"   # idle: at once
        await agent.stop()

    asyncio.run(go())


def test_no_picker_without_codex_profiles_or_for_claude(tmp_path):
    agent = Agent("acctest2", engine_argv={"claude": FAKE})
    assert agent.accounts is None and agent.info()["accounts"] is None
    with pytest.raises(AiifyError):
        asyncio.run(agent.request_account("b"))
    fake = FakeProfiles()
    claude = Agent("acctest3", codex_accounts=CodexAccounts(run=fake))
    claude.accounts.refresh()
    assert claude.info()["accounts"] is None               # the picker is for Codex only


def test_claude_limits_after_a_message(tmp_path):
    agent = Agent("acctest4", engine_argv={"claude": FAKE}, cwd=tmp_path / "w")

    async def go():
        await agent.start()
        await agent.send("hi")                       # the fake reports a 5h reading in _meta
        first = agent.info()["limits"]["providers"]["claude"]
        await asyncio.wait_for(agent._limit_task, 30)   # then /usage in a side session
        later = agent.info()["limits"]["providers"]["claude"]
        task = agent._limit_task
        await agent.send("hi")
        again = agent._limit_task is task            # not re-run within limit_check_every
        await agent.stop()
        return first, later, again

    first, later, again = asyncio.run(go())
    assert [(w["kind"], w["used"]) for w in first] == [("five_hour", 20.0)]
    assert [(w["kind"], w["used"], w["warn"]) for w in later] == [("five_hour", 14.0, False),
                                                                ("seven_day", 92.0, True)]
    assert again


def test_no_limit_checks_when_turned_off(tmp_path):
    agent = Agent("acctest5", engine_argv={"claude": FAKE}, cwd=tmp_path / "w", limit_check_every=None)

    async def go():
        await agent.start()
        await agent.send("hi")
        task = agent._limit_task
        await agent.stop()
        return task

    assert asyncio.run(go()) is None
