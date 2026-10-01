"""The panel's look options on the Python side: the script tag and inject=True."""
import pytest
from fastapi import FastAPI
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.testclient import TestClient

from aiify import Agent
from aiify.web import panel_tag

PAGE = "<html><body><h1>hi</h1></body></html>"


def test_panel_tag_options():
    assert panel_tag() == '<script src="/aiify/panel.js" defer></script>'
    tag = panel_tag("/x/", layout="float", opacity=80, open=True, accent='#2b6cb0"><b>')
    assert tag.startswith('<script src="/x/panel.js" defer data-layout="float" data-opacity="80" data-open="true"')
    assert 'data-accent="#2b6cb0&quot;&gt;&lt;b&gt;"' in tag          # escaped
    with pytest.raises(ValueError, match="unknown panel option"):
        panel_tag(colour="red")


def make(inject, panel=None):
    app = FastAPI()

    @app.get("/", response_class=HTMLResponse)
    def home():
        return PAGE

    @app.get("/own", response_class=HTMLResponse)
    def own():
        return PAGE.replace("</body>", '<script src="/aiify/panel.js"></script></body>')

    @app.get("/data")
    def data():
        return {"html": "</body>"}

    @app.get("/stream")
    def stream():
        return StreamingResponse(iter([b"<html><body>", b"part", b"</body></html>"]), media_type="text/html")

    Agent("looktest").mount(app, inject=inject, panel=panel)
    return app


def test_inject_adds_the_tag_to_html_pages_only():
    with TestClient(make(True, {"layout": "float", "opacity": 85})) as client:
        r = client.get("/")
        tag = '<script src="/aiify/panel.js" defer data-layout="float" data-opacity="85"></script>'
        assert r.text == PAGE.replace("</body>", tag + "</body>")
        assert int(r.headers["content-length"]) == len(r.content)
        assert client.get("/own").text.count("/aiify/panel.js") == 1            # already there
        assert client.get("/data").json() == {"html": "</body>"}                # not HTML
        assert client.get("/stream").text.count("/aiify/panel.js") == 1         # streamed pages too
        assert "/aiify/panel.js\" defer" not in client.get("/docs").text        # FastAPI's docs page
        assert "window.aiify" in client.get("/aiify/panel.js").text            # its own files untouched


def test_inject_can_choose_pages_and_is_off_by_default():
    with TestClient(make(lambda path: path == "/own")) as client:
        assert "panel.js" not in client.get("/").text
    with TestClient(make(False)) as client:
        assert client.get("/").text == PAGE
    with pytest.raises(ValueError):
        make(False, {"layuot": "float"})                    # a typo fails at mount, not silently
