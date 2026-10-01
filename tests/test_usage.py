"""Limit readings from recorded Claude ``_meta`` payloads and Codex rollouts."""
import os
import shutil
from pathlib import Path

from aiify import usage
from aiify.usage import (LimitWindow, UsageTracker, claude_from_meta, claude_from_usage_text,
                         codex_from_rollouts)

FIXTURE = Path(__file__).with_name("fixtures") / "codex_rollout.jsonl"
USAGE_MD = Path(__file__).with_name("fixtures") / "claude_usage.md"
# recorded during the engine spike (usage_update _meta)
SPIKE_META = {"_claude/rateLimit": {"status": "allowed_warning", "resetsAt": 1791090000,
                                    "rateLimitType": "seven_day", "utilization": 0.87,
                                    "isUsingOverage": False, "surpassedThreshold": 0.75}}
NOW = 1791000000.0


def test_claude_meta_from_the_spike():
    [w] = claude_from_meta(SPIKE_META, now=NOW)
    assert (w.provider, w.kind, w.used, w.resets_at, w.status) == \
        ("claude", "seven_day", 0.87, 1791090000, "allowed_warning")
    d = w.to_dict(NOW, warn_at=0.85)
    assert d["label"] == "week" and d["used"] == 87.0 and d["warn"] and d["resets_in_s"] == 90000
    assert not w.to_dict(NOW, warn_at=0.9)["warn"]


def test_claude_meta_without_utilization_and_odd_shapes():
    [w] = claude_from_meta({"_claude/rateLimit": {"status": "allowed", "rateLimitType": "five_hour"}})
    assert w.used is None and w.to_dict(NOW)["used"] is None and not w.to_dict(NOW)["warn"]
    rejected = claude_from_meta({"_claude/rateLimit": {"status": "rejected", "rateLimitType": "five_hour"}})
    assert rejected[0].to_dict(NOW)["warn"]
    for junk in (None, {}, {"_claude/rateLimit": "x"}, {"_claude/rateLimit": {"utilization": "lots"}}):
        assert claude_from_meta(junk) == []
    both = claude_from_meta({"unifiedWindows": {"five_hour": {"utilization": 0.1, "resetsAt": 5},
                                                "seven_day_opus": {"utilization": 0.5}}})
    assert {w.kind: w.used for w in both} == {"five_hour": 0.1, "seven_day_opus": 0.5}


def test_codex_rollouts(tmp_path):
    day = tmp_path / "sessions" / "2026" / "10" / "01"
    day.mkdir(parents=True)
    shutil.copy(FIXTURE, day / "rollout-2026-10-01T11-40-41-x.jsonl")
    usage._cache.clear()
    [w] = codex_from_rollouts(tmp_path)          # the newest record of the main pool wins
    assert (w.provider, w.kind, w.used, w.resets_at) == ("codex", "seven_day", 0.47, 1791122376)
    assert w.seen > 1.7e9                         # the record's own timestamp


def test_codex_home_env_and_missing_folder(tmp_path, monkeypatch):
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "nowhere"))
    assert usage.codex_home() == tmp_path / "nowhere"
    assert codex_from_rollouts() == []


def test_codex_older_two_window_format(tmp_path):
    lines = FIXTURE.read_text(encoding="utf-8").splitlines()[:2]
    found = usage.parse_codex(lines)
    assert found["windows"] == {"five_hour": {"pct": 12.0, "resets_at": 1791090000},
                                "seven_day": {"pct": 40.0, "resets_at": 1791122376}}


def test_tracker_merges_windows_and_forgets_on_account_switch():
    t = UsageTracker(warn_at=0.8)
    assert t.from_usage_event({"used": 1, "_meta": SPIKE_META})
    assert not t.from_usage_event({"used": 2, "_meta": SPIKE_META})      # nothing new
    assert t.from_usage_event({"_meta": {"_claude/rateLimit": {"rateLimitType": "five_hour", "utilization": 0.2}}})
    snap = t.snapshot(now=NOW)
    assert [w["kind"] for w in snap["providers"]["claude"]] == ["five_hour", "seven_day"]
    assert snap["providers"]["claude"][1]["warn"] and snap["warn_at"] == 0.8

    t.update([LimitWindow("codex", "seven_day", 0.5, None, seen=100.0)])
    t.forget("codex", since=200.0)
    assert "codex" not in t.snapshot()["providers"]
    assert not t.update([LimitWindow("codex", "seven_day", 0.5, None, seen=150.0)])   # old account
    assert t.update([LimitWindow("codex", "seven_day", 0.1, None, seen=250.0)])


def test_expired_window_reads_zero():
    w = LimitWindow("claude", "five_hour", 0.99, NOW - 5)
    d = w.to_dict(NOW)
    assert d["expired"] and d["used"] == 0.0 and not d["warn"]


def test_tests_never_read_the_real_codex_folder():
    assert Path(os.environ["CODEX_HOME"]).name == "codex-home"


def test_claude_usage_command_output():
    from datetime import datetime, timezone, timedelta
    now = datetime(2026, 10, 1, 13, 0, tzinfo=timezone(timedelta(hours=1))).timestamp()
    windows = claude_from_usage_text(USAGE_MD.read_text(encoding="utf-8"), now)
    got = [(w.kind, w.label, w.used) for w in windows]
    assert got == [("five_hour", "5h", 0.14), ("seven_day", "week", 0.9), ("seven_day_fable", "Fable week", 0.0)]
    gmt1 = timezone(timedelta(hours=1))
    assert windows[0].resets_at == datetime(2026, 10, 1, 17, 39, tzinfo=gmt1).timestamp()
    assert windows[1].resets_at == datetime(2026, 10, 4, 5, 59, tzinfo=gmt1).timestamp()
    assert windows[1].to_dict(now)["warn"] and windows[2].to_dict(now)["label"] == "Fable week"


def test_usage_text_odd_lines():
    now = 1791000000.0
    assert claude_from_usage_text("") == []
    assert claude_from_usage_text("**Cost** $0.00\n| a | b |") == []
    [w] = claude_from_usage_text("**Weekly · Opus** — **55%** · Resets sometime", now)
    assert (w.kind, w.used, w.resets_at) == ("seven_day_opus", 0.55, None)
    [w] = claude_from_usage_text("**5-hour limit** — **3%** · Resets 11:59 PM", now)
    assert w.resets_at and 0 < w.resets_at - now <= 86400
    [w] = claude_from_usage_text("**Weekly · all models** — **10%** · Resets Jan 2, 1 AM UTC", now)
    assert w.resets_at > now                                  # next year's date, not last year's
