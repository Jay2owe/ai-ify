"""Exercise the shared messaging controls without starting a model."""
import socket
import threading
import time

import pytest

pytestmark = pytest.mark.browser
playwright = pytest.importorskip("playwright.sync_api")
uvicorn = pytest.importorskip("uvicorn")


@pytest.fixture
def mail_server(tmp_path, monkeypatch):
    from fastapi import FastAPI
    from fastapi.responses import HTMLResponse
    from aiify import Agent, MessageHub
    from aiify.web import panel_tag

    def no_model(self):
        pass
    monkeypatch.setattr(Agent, "warm", no_model)
    hub = MessageHub(tmp_path / "messages.sqlite3")
    app = FastAPI()
    agents = {}
    for identity in ("analysis", "writing", "review"):
        agent = Agent("browser-" + identity, messaging=hub.mailbox(identity, label=identity.title()),
                      codex_accounts=None, prewarm=False)
        agent.mount(app, prefix="/" + identity + "/aiify")
        agents[identity] = agent
    @app.get("/{identity}")
    def page(identity: str):
        return HTMLResponse('<html><body style="margin:0"><div id="chat" style="height:100vh"></div>' +
                            panel_tag("/" + identity + "/aiify", layout="inline", target="#chat", open=True) +
                            "</body></html>")
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(200):
        if server.started:
            break
        time.sleep(.025)
    assert server.started
    try:
        yield f"http://127.0.0.1:{port}", agents
    finally:
        server.should_exit = True
        thread.join(10)
        assert not thread.is_alive()


def test_panel_send_live_notification_reply_and_layout(mail_server):
    url, agents = mail_server
    errors = []
    with playwright.sync_playwright() as runtime:
        try:
            browser = runtime.chromium.launch(channel="msedge", headless=True)
        except Exception:
            browser = runtime.chromium.launch(headless=True)
        try:
            a = browser.new_page(viewport={"width": 800, "height": 900})
            b = browser.new_page(viewport={"width": 300, "height": 900})
            for page, identity in ((a, "analysis"), (b, "writing")):
                page.on("pageerror", lambda error: errors.append(str(error)))
                page.goto(url + "/" + identity)
                page.get_by_role("button", name="Messages", exact=True).wait_for()
                page.get_by_placeholder("Ask the assistant...").wait_for()
            a.get_by_role("button", name="Messages", exact=True).click()
            a.get_by_label("Message recipient").select_option("writing")
            a.get_by_label("Message to another assistant").fill("Use the accepted method.")
            a.get_by_role("button", name="Send message", exact=True).click()
            b.get_by_role("button", name="Messages (new)", exact=True).wait_for()
            assert not b.get_by_label("Messages between assistants").is_visible()
            b.get_by_role("button", name="Messages (new)", exact=True).click()
            b.get_by_text("Use the accepted method.", exact=True).wait_for()
            b.get_by_role("button", name="Reply", exact=True).click()
            b.get_by_label("Message to another assistant").fill("I will cite it.")
            b.get_by_role("button", name="Send message", exact=True).click()
            a.get_by_role("button", name="Inbox", exact=True).click()
            a.get_by_text("I will cite it.", exact=True).wait_for()
            received = agents["analysis"].messaging.inbox()["items"][0]
            assert received["reply_to"] and received["thread_id"]
            a.get_by_role("button", name="Acknowledge", exact=True).click()
            a.get_by_text("Delivery history", exact=True).wait_for()
            assert agents["analysis"].messaging.inbox()["items"] == []
            # Changing recipients leaves reply mode; the old parent must not win.
            b.get_by_role("button", name="Reply", exact=True).click()
            b.get_by_label("Message recipient").select_option("review")
            b.get_by_label("Message to another assistant").fill("Independent review request.")
            b.get_by_role("button", name="Send message", exact=True).click()
            b.get_by_text("Message saved. The recipient can use it on their next turn.", exact=True).wait_for()
            review = agents["review"].messaging.inbox()["items"][0]
            assert review["reply_to"] is None
            for theme in ("light", "dark"):
                b.evaluate("(theme)=>document.querySelector('#aiify-root').setAttribute('data-theme',theme)", theme)
                assert b.locator("#aiify-root .panel").evaluate("(e)=>e.scrollWidth <= e.clientWidth + 1")
                assert b.get_by_placeholder("Ask the assistant...").is_visible()
            assert all(agent.session is None for agent in agents.values())
            assert not errors
        finally:
            browser.close()
