"""What the agent finds with no developer work: the app's routes as actions,
``aiify how`` over everything known, and the developer-built app map."""
import functools
import importlib
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from aiify import appmap
from aiify.cli import build_request
from aiify.protocol import AiifyError

FAKE = [sys.executable, str(Path(__file__).with_name("fake_acp_agent.py"))]

APP = '''
import sys
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from aiify import Agent

FAKE = {fake!r}
ROWS = [{{"id": 1, "name": "M01", "included": True}}, {{"id": 2, "name": "M02", "included": False}}]
app = FastAPI()


class Include(BaseModel):
    included: bool


@app.get("/", response_class=HTMLResponse)
def index():
    """The sample table."""
    return "<html><body>samples</body></html>"


@app.get("/api/samples")
def list_samples():
    """List the samples with their genotype."""
    return ROWS


@app.post("/api/samples/{{sample_id}}/include")
def include_sample(sample_id: int, body: Include):
    """Include or exclude one sample."""
    ROWS[sample_id - 1]["included"] = body.included
    return ROWS[sample_id - 1]


@app.post("/api/include_all")
def include_all():
    """Include every sample in the summary."""
    for row in ROWS:
        row["included"] = True
    return {{"ok": True}}


agent = Agent("{name}", engine_argv={{"claude": FAKE}}, limit_check_every=None, routes={routes})
agent.mount(app)
'''

README = """# Sample app

## Exporting
Use the Export button to save the table as a CSV file.
"""


def make_app(root: Path, name: str, routes="True") -> Path:
    pkg = root / name
    pkg.mkdir(parents=True)
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "main.py").write_text(APP.format(fake=FAKE, name=name, routes=routes), encoding="utf-8")
    (root / "README.md").write_text(README, encoding="utf-8")
    return pkg


@pytest.fixture
def sample(tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_ACP_STORE", str(tmp_path / "sessions.json"))
    monkeypatch.syspath_prepend(str(tmp_path))
    name = f"sampleapp_{tmp_path.name.replace('-', '_')}"
    pkg = make_app(tmp_path, name)
    module = importlib.import_module(f"{name}.main")
    yield module, pkg
    for key in [k for k in sys.modules if k.startswith(name)]:
        del sys.modules[key]


def test_routes_become_actions(sample):
    module, _ = sample
    agent = module.agent
    rows = {r["name"]: r for r in agent.actions.summaries()}
    assert set(rows) == {"route.list_samples", "route.include_sample", "route.include_all"}   # the page is not
    assert not rows["route.list_samples"]["mutates"] and rows["route.include_all"]["destructive"]
    assert rows["route.list_samples"]["summary"] == "List the samples with their genotype. (GET /api/samples)"
    params = agent.actions.source.describe("route.include_sample")["params"]
    assert params == [{"name": "sample_id", "required": True, "type": "integer"},
                      {"name": "included", "required": True, "type": "boolean"}]
    assert [p["path"] for p in agent.route_source.pages] == ["/"]


def test_running_routes_in_the_app(sample):
    module, _ = sample
    agent = module.agent
    with TestClient(module.app) as client:
        run = lambda name, params=None, confirm=False: client.portal.call(
            functools.partial(agent.actions.run, name, params or {}, confirm=confirm))
        assert run("route.list_samples")["result"][1]["name"] == "M02"
        with pytest.raises(AiifyError) as exc:
            run("route.include_all")                       # changes data: asks first
        assert exc.value.code == "requires_confirmation"
        assert run("route.include_all", confirm=True)["ok"]
        assert module.ROWS[1]["included"] is True
        reply = run("route.include_sample", {"sample_id": 2, "included": False}, confirm=True)
        assert reply["result"] == {"id": 2, "name": "M02", "included": False}
        bad = run("route.include_sample", {"sample_id": 2}, confirm=True)
        assert not bad["ok"] and "missing" in bad["error"]


def test_how_searches_actions_docs_and_pages(sample):
    module, _ = sample
    agent = module.agent
    with TestClient(module.app) as client:
        how = lambda q: client.portal.call(agent.how, q)
        top = how("how do I include every sample?")["results"][0]
        assert top["title"] == "route.include_all" and "action.run route.include_all" in top["use"]
        top = how("export the table to csv")["results"][0]
        assert top["kind"] == "docs" and top["title"] == "Exporting"
        assert how("sample table page")["results"][0]["kind"] == "page"
        assert how("zebra giraffe")["results"] == []
        assert how("include")["app_map"] is None


def test_routes_can_be_narrowed_or_turned_off(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(tmp_path))
    make_app(tmp_path / "a", "narrowapp", routes='["/api/samples*"]')
    monkeypatch.syspath_prepend(str(tmp_path / "a"))
    narrow = importlib.import_module("narrowapp.main")
    assert narrow.agent.actions.source.names() == ["route.include_sample", "route.list_samples"]
    make_app(tmp_path / "b", "noroutesapp", routes="False")
    monkeypatch.syspath_prepend(str(tmp_path / "b"))
    assert importlib.import_module("noroutesapp.main").agent.actions is None


def test_build_check_and_use_the_app_map(sample, capsys):
    module, pkg = sample
    target = f"{module.__name__}:app"
    assert appmap.check(target) == 1                       # none yet
    path = appmap.build(target, argv=FAKE)
    assert path == pkg / "aiify_map.md"
    text = path.read_text(encoding="utf-8")
    assert text.startswith("<!-- aiify app map: app=") and "\n# App map: sample" in text
    assert "Here is the map." not in text                  # only the map is kept
    assert appmap.check(target) == 0
    agent = module.agent
    with TestClient(module.app) as client, client.websocket_connect("/aiify/ws") as ws:
        ws.receive_json()
        got = client.portal.call(agent.how, "see the counts per genotype")
        assert got["results"][0]["title"] == "How to see counts per genotype" and got["app_map"] == "current"
        client.post("/aiify/api/send", json={"text": "echo hi"}, headers={"X-Aiify": "1"})
        sent = ""
        for _ in range(300):
            ev = ws.receive_json()
            sent += ev.get("text", "") if ev.get("kind") == "text" else ""
            if ev.get("kind") == "done":
                break
        assert "[App map overview]" in sent and "mouse samples" in sent
    (pkg / "main.py").write_text((pkg / "main.py").read_text() + "\n# changed\n", encoding="utf-8")
    assert appmap.check(target) == 1
    assert "out of date" in capsys.readouterr().out


def test_how_on_the_command_line():
    assert build_request(["how", "export", "the", "summary"]) == {"op": "how", "q": "export the summary"}
    with pytest.raises(ValueError):
        build_request(["how"])
