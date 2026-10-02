"""Comparing the agent with and without each discovery helper (aiify.evaluate)."""
import json

import pytest

from aiify import evaluate
from aiify.evaluate import Run, Task, all_of, ran, says
from aiify.prompting import build_message
from aiify.profile import Profile
from aiify.protocol import AiifyError

from test_discovery import sample  # noqa: F401 - the fixture


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
