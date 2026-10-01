"""The packaged usage guide: reads, search, errors, and the exported copies."""
import json
import subprocess
import sys
from pathlib import Path

from aiify import __version__, context

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


def test_exported_copies_are_current():
    data = json.loads((ROOT / "aiify_context.json").read_text(encoding="utf-8"))
    assert data == json.loads((ROOT / "src/aiify/aiify_context.json").read_text(encoding="utf-8"))
    assert (ROOT / "README_AI.md").read_text(encoding="utf-8") == \
        (ROOT / "src/aiify/README_AI.md").read_text(encoding="utf-8")
    exported = {t["topic"]: t["content"] for t in data["topics"]}
    assert exported == {t: context.read(t) for t in context.topics()}
