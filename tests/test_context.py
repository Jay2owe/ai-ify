"""The packaged usage guide: reads, search, errors, and the exported copies."""
import json
import ast
import asyncio
import inspect
import re
import subprocess
import sys
from dataclasses import fields
from pathlib import Path

from aiify import __version__, context
import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_every_topic_reads_as_text_and_json():
    for topic in context.topics():
        text = context.read(topic)
        assert text.startswith(f"ai-ify {__version__}")
        data = context.read(topic, format="json")
        assert data["ok"] and data["content"] == text
        json.dumps(data, allow_nan=False)
    overview = context.read("overview", format="json")
    assert [t["topic"] for t in overview["topics"]] == list(context.topics())
    assert context.read("quickstart", format="json")["prerequisites"] == ["setup"]


def test_unknown_and_malformed():
    bad = context.read("quickstrat", format="json")
    assert not bad["ok"] and "quickstart" in bad["suggestions"]
    assert not context.read("", format="json")["ok"]
    assert not context.read("overview", format="yaml")["ok"]
    assert context.search("")["results"] == []
    assert context.search("zebra hovercraft")["results"] == []


def test_search_finds_the_right_topic():
    assert context.search("approval card")["results"][0]["topic"] == "actions"
    assert context.search("disconnected retrying websocket")["results"][0]["topic"] == "troubleshooting"
    assert context.search("registerTool")["results"][0]["topic"] == "page-control"


def test_terminal_route():
    out = subprocess.run([sys.executable, "-m", "aiify.context", "setup"], capture_output=True, text=True)
    assert out.returncode == 0 and json.loads(out.stdout)["topic"] == "setup"


def test_integration_example_runs_without_a_real_agent():
    import re
    from fastapi.testclient import TestClient

    guide = context.read("integration")
    code = re.search(r"```python\n(.*?)\n```", guide, re.S).group(1)
    namespace = {"__name__": "guide_example"}
    exec(compile(code, "integration-example", "exec"), namespace)
    agent = namespace["agent"]
    with TestClient(namespace["app"]) as client:
        assert "/aiify/panel.js" in client.get("/").text
        result = agent.actions.source.run("notes.add", {"text": "hello"})
        assert result["ok"] and result["result"] == {"count": 1}
        assert agent.actions.source.run("notes.list", {})["result"] == {"notes": ["hello"]}
    assert any(r["topic"] == "integration" for r in context.search("embed another app")["results"])


def test_context_import_does_not_load_backend():
    code = ("import sys; from aiify import context; context.read('integration'); "
            "assert 'aiify.agent' not in sys.modules; "
            "assert 'aiify.web' not in sys.modules")
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def _example(topic, index=0):
    return re.findall(r"```python\n(.*?)\n```", context.read(topic), re.S)[index]


def test_feature_reference_covers_public_configuration():
    """A new embedding option must not silently be omitted from the public guide."""
    from aiify import Agent, Profile, Launch, When

    reference = context.read("features")
    for name in inspect.signature(Agent).parameters:
        assert f"`{name}`" in reference, f"Undocumented Agent option: {name}"
    for cls in (Profile, Launch, When):
        rows = "\n".join(line for line in reference.splitlines() if line.startswith(f"| `{cls.__name__}` |"))
        for field in fields(cls):
            assert f"`{field.name}`" in rows, f"Undocumented {cls.__name__} option: {field.name}"
    for topic in context.topics():
        info = context.read(topic, format="json")
        assert set(info["related"] + info["prerequisites"]) <= set(context.topics())
    assert context.topics()[0] == "overview"


def test_best_practices_recipe_permissions_and_context():
    from fastapi.testclient import TestClient
    from aiify.protocol import AiifyError

    namespace = {"__name__": "guide_recipe"}
    exec(compile(_example("best-practices"), "best-practices-example", "exec"), namespace)
    agent = namespace["agent"]
    with TestClient(namespace["app"]) as client:
        assert "data-aiify-launch" in client.get("/").text
        assert [row["name"] for row in agent.actions.summaries()] == ["notes.list"]
        with pytest.raises(AiifyError, match="not allowed"):
            client.portal.call(lambda: agent.actions.run("notes.add", {"text": "hello"}))
        client.portal.call(lambda: agent.configure(profile="editor"))
        assert client.portal.call(lambda: agent.actions.run("notes.add", {"text": "hello"}))["result"] == {"count": 1}
        with pytest.raises(AiifyError) as error:
            client.portal.call(lambda: agent.actions.run("notes.clear", {}))
        assert error.value.code == "requires_confirmation"
        assert namespace["notes"] == ["hello"]
        local = client.portal.call(lambda: agent.send("How many notes?"))
        assert local["by_app"] and agent.session is None
        summary = client.portal.call(lambda: agent.send("echo summary"))
        assert summary["stop"] == "end_turn"
        assert any("Use at most three bullet points." in e.get("text", "") for e in agent.history)
        client.portal.call(lambda: agent.launch("summarise"))
        assert agent.profile_name == "viewer"
        assert namespace["reply_log"]


@pytest.mark.parametrize("topic", ["actions", "messaging", "other-apps"])
def test_complete_standalone_examples(topic):
    # The first blocks in these topics illustrate wiring; their second blocks are complete.
    code = _example(topic, 1 if topic in ("other-apps", "messaging") else 0)
    exec(compile(code, f"{topic}-example", "exec"), {"__name__": "guide_example"})


def test_programmatic_events_and_structured_question(capsys, monkeypatch, tmp_path):
    # The standalone script owns its process environment; restore it when executed in pytest.
    monkeypatch.setenv("FAKE_ACP_STORE", str(tmp_path / "sessions.json"))
    namespace = {"__name__": "guide_example"}
    code = _example("programmatic")
    # Include the documented ask fragment in the same initialized agent lifecycle.
    code = code.replace("            print(\"\".join(parts))", "            print(\"\".join(parts))\n" +
                        "\n".join("            " + line for line in _example("programmatic", 2).splitlines()))
    exec(compile(code, "programmatic-example", "exec"), namespace)
    asyncio.run(namespace["main"]())
    assert "hello from fake" in capsys.readouterr().out


def test_all_guide_python_examples_have_valid_syntax():
    for topic in context.topics():
        for index, code in enumerate(re.findall(r"```python\n(.*?)\n```", context.read(topic), re.S)):
            compile(code, f"guide:{topic}:{index}", "exec", flags=ast.PyCF_ALLOW_TOP_LEVEL_AWAIT)


def test_documented_evaluation_check_fails_before_and_passes_after(tmp_path, monkeypatch):
    from aiify.evaluate import evaluate

    monkeypatch.syspath_prepend(str(tmp_path))
    monkeypatch.setitem(sys.modules, "example_app", None)
    del sys.modules["example_app"]
    (tmp_path / "example_app.py").write_text(_example("integration"), encoding="utf-8")
    tasks_path = tmp_path / "tasks.py"
    tasks_path.write_text(_example("evaluate", 1), encoding="utf-8")
    messages = []
    result = evaluate(tasks_path, out=tmp_path / "checks", mixes=["none"], check_tasks=True,
                      echo=messages.append)
    assert result == tmp_path / "checks"
    receipt = json.loads((result / "task-check.json").read_text(encoding="utf-8"))
    assert receipt["ok"], receipt
    assert receipt["tasks"][0]["before"][0] is False
    assert receipt["tasks"][0]["after"][0] is True


def test_exported_copies_are_current():
    data = json.loads((ROOT / "aiify_context.json").read_text(encoding="utf-8"))
    assert data == json.loads((ROOT / "src/aiify/aiify_context.json").read_text(encoding="utf-8"))
    assert (ROOT / "README_AI.md").read_text(encoding="utf-8") == \
        (ROOT / "src/aiify/README_AI.md").read_text(encoding="utf-8")
    exported = {t["topic"]: t["content"] for t in data["topics"]}
    assert exported == {t: context.read(t) for t in context.topics()}
