"""The page bridge in a real browser (headless Edge, else Playwright's Chromium),
against examples/demo_app.py with the scripted fake agent."""
import io
import json
import socket
import sys
import threading
import time
from pathlib import Path

import pytest

pytestmark = pytest.mark.browser
playwright = pytest.importorskip("playwright.sync_api")
uvicorn = pytest.importorskip("uvicorn")

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "examples"))
import demo_app  # noqa: E402

from aiify.cli import main as cli_main  # noqa: E402


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def server(tmp_path_factory):
    home = tmp_path_factory.mktemp("home")
    mp = pytest.MonkeyPatch()
    mp.setenv("AIIFY_HOME", str(home))
    mp.setenv("FAKE_ACP_STORE", str(home / "sessions.json"))
    app, agent, data = demo_app.build(fake=True)
    port = free_port()
    srv = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    t = threading.Thread(target=srv.run, daemon=True)
    t.start()
    for _ in range(200):
        if srv.started:
            break
        time.sleep(0.05)
    yield {"url": f"http://127.0.0.1:{port}/", "agent": agent, "data": data, "home": home}
    srv.should_exit = True
    t.join(10)
    mp.undo()


@pytest.fixture(autouse=True)
def same_home(server, monkeypatch):
    monkeypatch.setenv("AIIFY_HOME", str(server["home"]))      # the CLI must find the demo's port


@pytest.fixture(scope="module")
def browser():
    with playwright.sync_playwright() as p:
        try:
            b = p.chromium.launch(channel="msedge", headless=True)
        except Exception:
            b = p.chromium.launch(headless=True)
        yield b
        b.close()


@pytest.fixture
def page(server, browser):
    server["data"].reset()
    pg = browser.new_page()
    errors = []
    pg.on("pageerror", lambda e: errors.append(str(e)))
    pg.goto(server["url"])
    pg.wait_for_function("window.aiify && window.aiify.bridge")
    for _ in range(100):
        if server["agent"].relay.attached:
            break
        time.sleep(0.05)
    yield pg
    pg.close()
    assert not errors, errors
    for _ in range(100):                                       # wait for the page to detach
        if not server["agent"].relay.attached:
            break
        time.sleep(0.05)


def cli(*argv):
    buf = io.StringIO()
    code = cli_main(["--app", "aiify-demo", "--timeout=20", *argv], out=buf)
    return code, json.loads(buf.getvalue())


def by_label(elements, text):
    return next(e for e in elements if e["label"] == text)


def test_tree_names_first_hides_off_and_panel(page):
    code, out = cli("ui", "tree")
    assert code == 0, out
    els = out["result"]["elements"]
    refs = [e["ref"] for e in els]
    assert refs[:2] == ["view-picker", "reset-button"]
    assert by_label(els, "Include all")["ref"].startswith("e")
    assert els[0]["role"] == "combobox" and els[0]["value"] == "table"
    labels = " ".join(e["label"] for e in els)
    assert "Delete everything" not in labels                    # data-agent="off"
    assert "New chat" not in labels and "Send" not in labels    # the panel itself
    assert page.locator("#playwright-highlight-container *").count() == 0


def test_click_by_numbered_ref_and_stale_refs(page, server):
    server["data"].rows[2]["included"] = False
    _, out = cli("ui", "tree", "match=include")
    ref = by_label(out["result"]["elements"], "Include all")["ref"]
    code, out = cli("ui", "click", ref)
    assert code == 0 and out["result"] == {"clicked": ref}
    page.wait_for_timeout(300)
    assert all(r["included"] for r in server["data"].rows)
    assert page.locator("#aiify-flash").count() == 1
    # the click changed the page, so the old numbered ref is stale; names never are
    page.wait_for_function("document.querySelectorAll('tr[data-id]').length > 0")
    cli("ui", "do", "show_view", "view=summary")
    code, out = cli("ui", "click", ref)
    assert out["code"] == "stale_ref"
    code, out = cli("ui", "read", "view-picker")
    assert out["result"]["value"] == "summary"


def test_named_ui_commands(page):
    code, out = cli("describe")
    names = [c["name"] for c in out["result"]["levels"]["ui_commands"]["commands"]]
    assert names == ["show_view", "select_sample"]
    code, out = cli("ui", "do", "show_view", "view=summary")
    assert code == 0 and out["result"] == {"view": "summary"} and out["screen_changed"]
    assert "Included samples by genotype" in page.inner_text("#out")
    assert cli("ui", "do", "show_view", "view=nope")[1]["code"] == "invalid"
    assert cli("ui", "do", "show_view")[1]["code"] == "invalid"
    assert cli("ui", "do", "fly")[1]["code"] == "not_found"
    code, out = cli("ui", "do", "select_sample", "id=2")
    assert out["result"] == {"selected": 2}
    code, out = cli("state")
    assert out["result"]["view"] == "table" and out["result"]["selected"] == 2
    assert len(out["result"]["samples"]) == 3                  # backend state merged in


def test_select_fill_and_off_regions(page):
    code, out = cli("ui", "select", "view-picker", "value=summary")
    assert code == 0 and out["result"]["value"] == "summary"
    assert page.input_value("#view") == "summary"
    assert "genotype" in page.inner_text("#out")
    assert cli("ui", "select", "view-picker", "value=nothing")[1]["code"] == "not_found"
    # a control named inside an off region is still refused
    page.evaluate("document.getElementById('wipe').setAttribute('data-agent', 'wipe-button')")
    code, out = cli("ui", "click", "wipe-button")
    assert out["code"] == "denied"
    assert cli("ui", "click", "no-such-name")[1]["code"] == "not_found"
    code, out = cli("ui", "scroll", "direction=down")
    assert code == 0 and out["result"]["scrolled"] == "page"


def test_fill_a_text_box(page):
    page.evaluate("""() => { const i = document.createElement('input'); i.placeholder = 'Search samples';
        i.addEventListener('input', () => { window._typed = i.value; }); document.body.prepend(i); }""")
    _, out = cli("ui", "tree", "match=search")
    ref = out["result"]["elements"][0]["ref"]
    code, out = cli("ui", "fill", ref, "M02")
    assert code == 0 and out["result"]["value"] == "M02"
    assert page.evaluate("window._typed") == "M02"


def test_closing_the_page_gives_no_ui(server, browser):
    pg = browser.new_page()
    pg.goto(server["url"])
    pg.wait_for_function("window.aiify && window.aiify.bridge")
    time.sleep(0.5)
    assert cli("ui", "tree")[0] == 0
    pg.close()
    for _ in range(100):
        if not server["agent"].relay.attached:
            break
        time.sleep(0.05)
    assert cli("ui", "tree")[1]["code"] == "no_ui"
    assert cli("action.list")[0] == 0


def test_limit_bars_and_account_picker(page, server):
    from aiify.accounts import CodexAccounts
    from aiify.usage import claude_from_meta, LimitWindow
    agent = server["agent"]
    page.evaluate("window.aiify.open()")
    agent.usage.update(claude_from_meta({"_claude/rateLimit": {
        "status": "allowed_warning", "rateLimitType": "seven_day", "utilization": 0.95, "resetsAt": 4102444800}}))
    agent.usage.update(claude_from_meta({"_claude/rateLimit": {"rateLimitType": "five_hour", "utilization": 0.3}}))
    agent.emit(kind="info", info=agent.info())
    bars = page.locator("#aiify-root .limit")
    page.wait_for_function("document.getElementById('aiify-root').shadowRoot.querySelectorAll('.limit').length == 2")
    assert bars.nth(0).inner_text().split() == ["5h", "30%"]
    assert "95%" in bars.nth(1).inner_text() and "resets" in bars.nth(1).inner_text()
    assert "warn" in bars.nth(1).get_attribute("class") and "warn" not in bars.nth(0).get_attribute("class")
    assert not page.locator("#aiify-root select[title^='Saved Codex']").is_visible()

    rows = [{"id": "a", "label": "Lab", "is_current": True}, {"id": "b", "label": "Home", "is_current": False}]
    accounts = CodexAccounts(run=lambda *a: {"profiles": rows})
    accounts.refresh()
    old = agent.accounts, agent.provider
    try:
        agent.accounts, agent.provider = accounts, "codex"
        agent.usage.update([LimitWindow("codex", "seven_day", 0.47, None)])
        agent.emit(kind="info", info=agent.info())
        picker = page.locator("#aiify-root select[title^='Saved Codex']")
        picker.wait_for(state="visible")
        assert picker.locator("option").all_inner_texts() == ["Lab", "Home"]
        assert page.locator("#aiify-root .limit").all_inner_texts() == ["week\n47%"]
    finally:
        agent.accounts, agent.provider = old
        agent.usage.forget("codex")
        agent.usage.forget("claude")
        agent.emit(kind="info", info=agent.info())


def test_signin_card(page, server, monkeypatch):
    agent = server["agent"]
    asked = []

    async def sign_in(method=None):
        asked.append(method)
        agent.signin["waiting"] = method
        agent.emit(kind="info", info=agent.info())
        return {"waiting": method}

    monkeypatch.setattr(agent, "sign_in", sign_in)
    page.evaluate("window.aiify.open()")
    card = page.locator("#aiify-root .signin")
    try:
        agent.signin = {"provider": "claude", "waiting": None,
                        "methods": [{"id": "claude-ai-login", "name": "Claude Subscription", "description": "", "type": "terminal"}]}
        agent.emit(kind="info", info=agent.info())
        card.wait_for(state="visible")
        assert "Sign in to Claude" in card.inner_text()
        card.get_by_role("button", name="Sign in").click()
        card.get_by_role("button", name="I've signed in").wait_for()
        assert asked == ["claude-ai-login"] and "Waiting for you" in card.inner_text()
        assert page.locator("#aiify-root .status").inner_text() == "signed out"
    finally:
        agent.signin = None
        agent.emit(kind="info", info=agent.info())
    card.wait_for(state="hidden")
