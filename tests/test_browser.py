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
    asked, codes = [], []

    async def sign_in(method=None):
        asked.append(method)
        agent.signin.update(waiting=method, link="https://example.test/login", code=True)
        agent.emit(kind="info", info=agent.info())
        return {"waiting": method}

    async def send_signin_code(code):
        codes.append(code)
        return {"sent": True}

    monkeypatch.setattr(agent, "sign_in", sign_in)
    monkeypatch.setattr(agent, "send_signin_code", send_signin_code)
    page.evaluate("window.aiify.open()")
    card = page.locator("#aiify-root .signin")
    try:
        agent.signin = {"provider": "claude", "waiting": None, "link": None, "code": False,
                        "methods": [{"id": "claude-ai-login", "name": "Claude Subscription", "description": "", "type": "terminal"}]}
        agent.emit(kind="info", info=agent.info())
        card.wait_for(state="visible")
        assert "Sign in to Claude" in card.inner_text()
        card.get_by_role("button", name="Sign in").click()
        link = card.get_by_role("link", name="Open the sign-in page")
        link.wait_for()
        assert asked == ["claude-ai-login"] and link.get_attribute("href") == "https://example.test/login"
        box = card.get_by_placeholder("Paste the code here")
        box.fill("ABC123")
        agent.emit(kind="info", info=agent.info())         # an unrelated update keeps the typed code
        assert box.input_value() == "ABC123"
        card.get_by_role("button", name="Continue").click()
        for _ in range(100):
            if codes:
                break
            time.sleep(0.05)
        assert codes == ["ABC123"]
        assert page.locator("#aiify-root .status").inner_text() == "signed out"
    finally:
        agent.signin = None
        agent.emit(kind="info", info=agent.info())
    card.wait_for(state="hidden")


ROOT_JS = "document.getElementById('aiify-root').shadowRoot"


def panel_rect(page):
    return page.evaluate(f"(() => {{ const r = {ROOT_JS}.querySelector('.panel').getBoundingClientRect();"
                         " return {x: r.left, y: r.top, w: r.width, h: r.height}; })()")


def test_window_layout_drags_and_is_remembered(page, server):
    try:
        page.evaluate("window.aiify.setLayout('float'); window.aiify.open()")
        start = panel_rect(page)
        assert start["x"] > 0 and start["y"] > 0 and start["h"] < page.viewport_size["height"]
        page.mouse.move(start["x"] + 40, start["y"] + 12)        # the title bar
        page.mouse.down()
        page.mouse.move(start["x"] - 160, start["y"] + 62, steps=5)
        page.mouse.up()
        moved = panel_rect(page)
        assert abs(moved["x"] - (start["x"] - 200)) < 2 and abs(moved["y"] - (start["y"] + 50)) < 2
        page.reload()
        page.wait_for_function("window.aiify && window.aiify.bridge")
        page.wait_for_function(f"!{ROOT_JS}.querySelector('.panel').hidden")
        again = panel_rect(page)
        assert abs(again["x"] - moved["x"]) < 2 and abs(again["y"] - moved["y"]) < 2
        assert page.evaluate(f"{ROOT_JS}.querySelector('select[title=\"Where the panel sits\"]').value") == "float"
    finally:
        page.evaluate("window.aiify.setLayout('overlay'); window.aiify.close()")


def test_opacity_thins_the_background_not_the_text(page):
    try:
        page.evaluate("window.aiify.open()")
        slider = page.locator("#aiify-root input[type=range]")
        slider.fill("50")
        bg = page.evaluate(f"getComputedStyle({ROOT_JS}.querySelector('.panel')).backgroundColor")
        ink = page.evaluate(f"getComputedStyle({ROOT_JS}.querySelector('.title')).color")
        assert ("/ 0.5)" in bg) or (", 0.5)" in bg), bg
        assert "/ 0" not in ink and ink.count(",") == 2, ink          # rgb(), fully solid
    finally:
        page.evaluate("window.aiify.setOpacity(100); window.aiify.close()")


def test_docked_layout_moves_the_page_aside(page):
    try:
        page.evaluate("window.aiify.setLayout('dock'); window.aiify.open()")
        width = panel_rect(page)["w"]
        margin = page.evaluate("parseFloat(getComputedStyle(document.documentElement).marginRight)")
        assert abs(margin - width) < 2
        page.evaluate("window.aiify.close()")
        assert page.evaluate("parseFloat(getComputedStyle(document.documentElement).marginRight)") == 0
    finally:
        page.evaluate("window.aiify.setLayout('overlay'); window.aiify.close()")


def test_inline_panel_own_launcher_and_accent(server, browser):
    pg = browser.new_page()
    url = server["url"] + "inline-test"
    pg.route(url, lambda route: route.fulfill(content_type="text/html", body=(
        '<html><body><div id="ai" style="width:520px;height:420px;margin:30px"></div>'
        '<script src="/aiify/panel.js" defer data-layout="inline" data-target="#ai" '
        'data-launcher="none" data-accent="#ff0000"></script></body></html>')))
    try:
        pg.goto(url)
        pg.wait_for_function("window.aiify && window.aiify.panel")
        pg.wait_for_function(f"!{ROOT_JS}.querySelector('.panel').hidden")
        assert pg.evaluate("document.getElementById('aiify-root').parentElement.id") == "ai"
        r = panel_rect(pg)
        box = pg.evaluate("(() => { const b = document.getElementById('ai').getBoundingClientRect();"
                          " return {x: b.left, y: b.top}; })()")
        assert abs(r["x"] - box["x"]) < 2 and abs(r["y"] - box["y"]) < 2
        assert abs(r["w"] - 520) < 2 and abs(r["h"] - 420) < 2
        assert pg.evaluate(f"{ROOT_JS}.querySelector('.launcher').hidden")
        assert not pg.locator("#aiify-root select[title='Where the panel sits']").is_visible()
        assert pg.evaluate(f"getComputedStyle({ROOT_JS}.querySelector('.composer .primary')).backgroundColor") == "rgb(255, 0, 0)"
    finally:
        pg.close()
