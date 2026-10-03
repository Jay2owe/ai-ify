"""Comparing the agent with and without each discovery helper (aiify.evaluate)."""
import json

import pytest

from aiify import evaluate
from aiify.evaluate import Run, Task, all_of, ran, says
from aiify.prompting import build_message
from aiify.profile import Profile
from aiify.protocol import AiifyError

from test_discovery import sample  # noqa: F401 - the fixture
from test_prepare import backend, bundle  # noqa: F401 - fixtures: a generated bundle


def test_helpers_switch_off_and_back_on(sample, tmp_path):  # noqa: F811
    module, pkg = sample
    agent = module.agent
    routes = lambda: [r["name"] for r in agent.actions.summaries() if r["name"].startswith("route.")]
    assert "route.include_all" in routes()
    map_file = tmp_path / "aiify_map.md"
    map_file.write_text("<!-- aiify app map: app=x sources=0 built=2026-10-02 by=test -->\n"
                        "# App map: x\n\n## Overview\nA sample table.\n", encoding="utf-8")
    agent._app_map_setting, agent._app_map = map_file, False
    assert agent.helpers() == {"routes": True, "how": True, "app_map": True}

    assert agent.set_helpers(routes=False, how=False, app_map=False) == {
        "routes": False, "how": False, "app_map": False}
    assert routes() == []
    with pytest.raises(AiifyError) as exc:
        import asyncio
        asyncio.run(agent._op_how({"q": "include every sample"}))
    assert exc.value.code == "not_supported"
    msg = build_message("hi", app="x", profile=Profile(), first=True, command="aiify --app x", how=False)
    assert 'how "plain question"' not in msg

    agent.set_helpers(routes=True, how=True, app_map=True)
    assert "route.include_all" in routes() and agent.app_map() is not None


def test_checks():
    run = Run(task="t", mix="all", prompt="p", reply="Use the Publication page to export a PDF.",
              state={}, commands=[{"title": "aiify --app x how \"pdf\"", "status": "completed"},
                                  {"title": "aiify --app x action.run route.wipe", "status": "failed"}],
              approvals=[], summary={}, seconds=1.0)
    assert says("publication", "PDF")(run) == (True, "")
    assert says("Figure")(run) == (False, "missing: Figure")
    assert ran(r"\bhow\b")(run)[0] and not ran(r"route\.wipe")(run)[0]       # failed commands don't count
    assert all_of(says("pdf"), ran("nothing"))(run)[0] is False


TASKS = '''
from aiify.evaluate import Task, says
APP = "{app}"
PAGE = None
TASKS = [Task("told-about-how", "echo what can you do?", check=says('how "plain question"'))]
'''


def test_evaluate_compares_mixes_and_reports(sample, tmp_path):  # noqa: F811
    module, pkg = sample
    tasks = tmp_path / "tasks.py"
    tasks.write_text(TASKS.format(app=f"{pkg.name}.main:app"), encoding="utf-8")
    out = evaluate.evaluate(tasks, out=tmp_path / "out", mixes=["all", "no-how"], page=False,
                            timeout=60, echo=lambda *a: None)
    rows = [json.loads(line) for line in (out / "runs.jsonl").read_text(encoding="utf-8").splitlines()]
    assert {(r["mix"], r["passed"]) for r in rows} == {("all", True), ("no-how", False)}
    assert rows[0]["helpers"]["how"] is True and rows[1]["helpers"]["how"] is False
    report = (out / "report.md").read_text(encoding="utf-8")
    assert "| how | 100% | 0% | +100 points |" in report
    assert "| told-about-how | 1/1 | 0/1 |" in report

    # a resumed round skips what is done and keeps one report over everything
    evaluate.evaluate(tasks, out=out, mixes=["all", "no-how", "none"], page=False, timeout=60,
                      resume=True, echo=lambda *a: None)
    rows = [json.loads(line) for line in (out / "runs.jsonl").read_text(encoding="utf-8").splitlines()]
    assert [r["mix"] for r in rows] == ["all", "no-how", "none"]


def test_unanswered_chats_are_not_counted_and_run_again(sample, tmp_path):  # noqa: F811
    module, pkg = sample
    tasks = tmp_path / "tasks.py"
    tasks.write_text(TASKS.format(app=f"{pkg.name}.main:app"), encoding="utf-8")
    out = tmp_path / "out"
    out.mkdir()
    limit = {"task": "told-about-how", "mix": "all", "repeat": 1, "passed": False,
             "note": "error: Internal error", "helpers": {}, "provider": "codex", "settings": {},
             "seconds": 6.0, "stop": "error: Internal error", "commands": [], "failed_commands": 0,
             "approvals": [], "reply": "You've hit your usage limit.", "state": {}}
    (out / "runs.jsonl").write_text(json.dumps(limit) + "\n", encoding="utf-8")
    report = evaluate.write_report(out).read_text(encoding="utf-8")
    assert "**Not counted:** 1 chat(s)" in report and "| all |" not in report

    evaluate.evaluate(tasks, out=out, mixes=["all"], page=False, timeout=60, resume=True, echo=lambda *a: None)
    rows = [json.loads(line) for line in (out / "runs.jsonl").read_text(encoding="utf-8").splitlines()]
    assert [r["passed"] for r in rows] == [False, True]          # run again, and the new row wins
    report = (out / "report.md").read_text(encoding="utf-8")
    assert "Not counted" not in report and "| told-about-how | 1/1 |" in report


def test_a_prepared_bundle_is_one_more_helper(sample, bundle, tmp_path):  # noqa: F811
    from aiify import prepare
    assert prepare.verify(bundle, echo=lambda *a: None)["ok"]
    module, pkg = sample
    tasks = tmp_path / "tasks.py"
    tasks.write_text(TASKS.format(app=f"{pkg.name}.main:app")
                     .replace('check=says(\'how "plain question"\')', 'check=says("value.clear")')
                     + f"PREPARED = {str(bundle)!r}\n"
                     + "def use_prepared(prepared, app):\n    prepared.module.WIRED_TO = app\n", encoding="utf-8")
    out = evaluate.evaluate(tasks, out=tmp_path / "out", mixes=["all", "no-prepared"], page=False,
                            timeout=60, echo=lambda *a: None)
    rows = [json.loads(line) for line in (out / "runs.jsonl").read_text(encoding="utf-8").splitlines()]
    assert [(r["mix"], r["helpers"]["prepared"], r["passed"]) for r in rows] == [
        ("all", True, True), ("no-prepared", False, False)]
    report = (out / "report.md").read_text(encoding="utf-8")
    assert "| prepared | 100% | 0% | +100 points |" in report
    import sys
    wired = [m for n, m in sys.modules.items() if n.startswith("_aiify_prepared_") and hasattr(m, "WIRED_TO")]
    assert wired and wired[-1].WIRED_TO is module.app                 # the tasks file's use_prepared ran
    names = [r["name"] for r in module.agent.actions.summaries()]
    assert "value.read" not in names and "prepared actions" not in module.agent.guide_text()   # switched off last
    plain = tasks.with_name("plain.py")
    plain.write_text(TASKS.format(app=f"{pkg.name}.main:app"), encoding="utf-8")
    with pytest.raises(SystemExit, match="unknown mix"):
        evaluate.evaluate(plain, mixes=["no-prepared"], page=False)


CHECKED = '''
from aiify.evaluate import Task, says
APP = "{app}"
PAGE = None
TASKS = [Task("good", "p", check=says("forty-two"), solve=lambda ctx: "It is forty-two."),
         Task("always-passes", "p", check=lambda run: True, solve=lambda ctx: ""),
         Task("unsolvable", "p", check=says("forty-two"), solve=lambda ctx: "no idea"),
         Task("no-solve", "p", check=says("x"))]
'''


def test_check_tasks_without_an_agent(sample, tmp_path):  # noqa: F811
    module, pkg = sample
    tasks = tmp_path / "tasks.py"
    tasks.write_text(CHECKED.format(app=f"{pkg.name}.main:app"), encoding="utf-8")
    assert evaluate.main([str(tasks), "--out", str(tmp_path / "out"), "--no-page", "--check-tasks"]) == 1
    got = json.loads((tmp_path / "out" / "task-check.json").read_text(encoding="utf-8"))
    problems = {r["task"]: r.get("problem", "") for r in got["tasks"]}
    assert problems["good"] == ""
    assert "passes before" in problems["always-passes"]
    assert "fails after solve" in problems["unsolvable"]
    assert "no solve" in problems["no-solve"]
    assert not (tmp_path / "out" / "runs.jsonl").exists()          # no chat was started


def test_a_short_usage_window_is_waited_out_and_a_long_one_ends_the_round():
    from types import SimpleNamespace
    def agent(*rows):
        return SimpleNamespace(usage=SimpleNamespace(snapshot=lambda: {"providers": {"claude": list(rows)}}))
    five = {"kind": "five_hour", "label": "5h", "used": 80.0, "expired": False, "resets_in_s": 1200}
    week = {"kind": "seven_day", "label": "week", "used": 75.0, "expired": False, "resets_in_s": 90000}
    low = {**week, "used": 10.0}
    assert evaluate._usage_high(agent(low), "claude", 70) is None
    assert evaluate._usage_high(agent(five, low), "claude", 70)[1] == 1200.0     # wait for the reset
    assert evaluate._usage_high(agent(five, week), "claude", 70)[1] is None      # stop
