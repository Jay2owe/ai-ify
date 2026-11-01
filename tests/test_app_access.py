"""access="app": the agent gets the app's tools and nothing else (no shell, files or web)."""
import asyncio
import json
import sys
from pathlib import Path

import pytest

import aiify
from aiify import Agent
from aiify.actions import from_functions
from aiify.engine import AcpSession, app_tool_server

FAKE = [sys.executable, str(Path(__file__).with_name("fake_acp_agent.py"))]
PNG = bytes.fromhex("89504e470d0a1a0a0000000d4948445200000001000000010806000000"
                    "1f15c4890000000d49444154789c6360000002000154a24f5d0000000049454e44ae426082")


@pytest.fixture(autouse=True)
def fake_store(tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_ACP_STORE", str(tmp_path / "sessions.json"))
    # the fake agent runs this copy of ai-ify, not an installed one without its new replies
    monkeypatch.setenv("PYTHONPATH", str(Path(aiify.__file__).resolve().parent.parent))


def make_agent(calls, **kw):
    def add(x: int):
        """Add a number."""
        calls.append(("add", x))
        return {"total": x}

    def wipe():
        """Delete everything."""
        calls.append(("wipe",))
        return "wiped"

    return Agent("apptools", actions=from_functions({"add": add, "wipe": wipe}, destructive=["wipe"]),
                 access="app", engine_argv={"claude": FAKE}, codex_accounts=None,
                 limit_check_every=None, app_map=None, **kw)


async def ask(agent, text):
    queue = agent.subscribe()
    await agent.send(text)
    out = []
    while not queue.empty():
        event = queue.get_nowait()
        if event.get("kind") == "text":
            out.append(event["text"])
    return "".join(out)


def test_session_gets_the_app_tool_server_and_no_builtin_tools():
    async def go():
        agent = make_agent([])
        await agent.start()
        try:
            return json.loads(await ask(agent, "show-setup"))
        finally:
            await agent.stop()
    setup = asyncio.run(go())
    (server,) = setup["mcp"]
    assert server["name"] == "app" and server["args"][:2] == ["-m", "aiify.tool_server"]
    assert server["command"] == sys.executable and server["env"]["AIIFY_HOME"]
    options = setup["meta"]["claudeCode"]["options"]
    assert options["tools"] == [] and options["settingSources"] == []      # no built-in tools, no CLAUDE.md
    assert options["allowedTools"] == ["mcp__app"]


def test_agent_runs_actions_through_the_tool_server_and_keeps_the_approval_step():
    calls = []

    async def go():
        agent = make_agent(calls)
        await agent.start()
        try:
            added = await ask(agent, 'call-tool action_run {"name": "add", "params": {"x": 2}}')
            asked = await ask(agent, 'call-tool action_run {"name": "wipe"}')
            before = list(calls)
            done = await ask(agent, 'call-tool action_run {"name": "wipe", "confirm": true}')
            return added, asked, before, done
        finally:
            await agent.stop()
    added, asked, before, done = asyncio.run(go())
    tools = added.split(" result=")[0].removeprefix("tools=").split(",")
    assert {"app_describe", "app_state", "action_list", "action_describe", "action_run", "how"} <= set(tools)
    assert not any(t.startswith(("messages_", "notes_")) for t in tools)      # this app has neither
    assert json.loads(added.split(" result=", 1)[1])["ok"]
    assert json.loads(asked.split(" result=", 1)[1])["code"] == "requires_confirmation"
    assert before == [("add", 2)]                                           # not wiped until confirmed
    assert json.loads(done.split(" result=", 1)[1])["ok"] and calls[-1] == ("wipe",)


def test_first_message_teaches_the_tools_not_the_shell_command():
    async def go():
        agent = make_agent([], notes=True)
        await agent.start()
        try:
            return await ask(agent, "echo")
        finally:
            await agent.stop()
    text = asyncio.run(go())
    assert "Your tools are this app's own" in text and "no shell" in text
    assert "-m aiify --app" not in text and "the notes_add tool" in text


def test_attached_image_goes_into_the_message():
    async def go():
        agent = make_agent([], attachments=True)
        await agent.start()
        try:
            agent.attachments.add("figure.png", data=PNG)
            agent.attachments.add("notes.txt", data=b"line one\nline two")
            agent.attachments.add("figure2.png", data=PNG)
            return await ask(agent, "count-images")
        finally:
            await agent.stop()
    assert asyncio.run(go()) == "images=2"


def test_attached_text_is_inlined_for_an_agent_that_cannot_open_files(tmp_path):
    from aiify.attachments import Attachments, attached_text
    box = Attachments(lambda: tmp_path)
    box.add("data.csv", data=("a,b\n" + "1,2\n" * 3000).encode())
    box.add("figure.png", data=PNG)
    box.add("blob.bin", data=b"\xff\xfe\x00")
    text = attached_text(box.take(), readable=False)
    assert "You cannot open files" in text and text.count("1,2") == 3000
    assert "(image, sent with this message)" in text and "only its path can be used" in text


def test_codex_gets_its_shell_and_extras_switched_off_and_the_tool_server(tmp_path, monkeypatch):
    home = Path(__import__("os").environ["CODEX_HOME"])
    home.mkdir(parents=True, exist_ok=True)
    (home / "config.toml").write_text('[mcp_servers.gmail]\ncommand = "gmail-mcp"\n', encoding="utf-8")
    session = AcpSession("codex", cwd=tmp_path, argv=FAKE, app_tools=app_tool_server("apptools@1"))
    config = json.loads(session.env["CODEX_CONFIG"])
    features = config["features"]
    assert features["shell_tool"] is False and features["unified_exec"] is False
    assert features["view_image"] is False and features["apps"] is False and features["memories"] is False
    assert config["web_search"] == "disabled" and config["sandbox_mode"] == "read-only"
    assert config["project_doc_max_bytes"] == 0
    assert config["mcp_servers"]["gmail"] == {"enabled": False}             # the person's own stays off
    assert config["mcp_servers"]["app"]["args"] == ["-m", "aiify.tool_server", "--app", "apptools@1"]
    assert config["mcp_servers"]["app"]["default_tools_approval_mode"] == "approve"
    assert config["approvals_reviewer"] == "user"                           # no reviewer model per call
    assert session._mcp_servers == [] and session._session_meta == {}       # not sent in the request
    assert session.settings["mode"] == "read-only"
    session._conn, session.config = object(), {"mode": {"value": "read-only", "choices": ["read-only", "agent"]}}
    with pytest.raises(ValueError, match="read-only"):
        asyncio.run(session.set_option("mode", "agent"))


@pytest.mark.parametrize("title, allowed", [("mcp.app.action_run", True), ("mcp__app__action_run", True),
                                            ("Edit files", False), ("mcp.gmail.send", False)])
def test_permission_outside_the_app_is_refused_without_asking(tmp_path, title, allowed):
    from acp import schema
    session = AcpSession("codex", cwd=tmp_path, argv=FAKE, app_tools=app_tool_server("apptools@1"),
                         permission_handler=lambda request: pytest.fail("the person was asked"))
    events = []
    session.on_event = events.append
    options = [schema.PermissionOption(option_id="yes", name="Yes", kind="allow_once"),
               schema.PermissionOption(option_id="no", name="No", kind="reject_once")]
    reply = asyncio.run(session.request_permission(
        "s", schema.ToolCallUpdate(tool_call_id="t", title=title), options))
    assert (getattr(reply.outcome, "option_id", None) == "yes") is allowed
    assert any("Refused" in e.get("text", "") for e in events) is not allowed


def test_full_access_is_unchanged_by_default(tmp_path):
    session = AcpSession("claude", cwd=tmp_path, argv=FAKE, user_mcp=False)
    assert session._mcp_servers == []
    assert session._session_meta == {"claudeCode": {"options": {"strictMcpConfig": True}}}
    with pytest.raises(ValueError, match="access"):
        Agent("x", access="files", codex_accounts=None, limit_check_every=None)


def test_images_an_action_returns_are_sent_but_a_bare_path_is_never_opened(tmp_path):
    from aiify import ImageFile
    from aiify.protocol import serialize
    from aiify.tool_server import Server
    preview, secret = tmp_path / "preview.png", tmp_path / "private.png"
    preview.write_bytes(PNG)
    secret.write_bytes(PNG)
    result = serialize({"preview": ImageFile(preview), "echoed": {"aiify_image": str(secret)},
                        "notes": ImageFile(tmp_path / "notes.txt")})
    server = Server("apptools")
    server.request = lambda op, fields: {"ok": True, "result": result}
    content = server.call("action_run", {"name": "drawing.preview"})["content"]
    images = [c for c in content if c["type"] == "image"]
    assert len(images) == 1 and images[0]["mimeType"] == "image/png"        # the app's preview only
    text = json.loads(content[0]["text"])
    assert "data" not in text["result"]["preview"] and text["result"]["preview"]["aiify_image"] == str(preview)
    assert "not a PNG" in text["result"]["notes"]["error"]


def test_the_aiify_command_prints_an_image_path_not_its_data():
    from aiify.protocol import without_image_data
    reply = {"ok": True, "result": {"preview": {"aiify_image": "p.png", "mime_type": "image/png", "data": "xx"},
                                    "data": "kept"}}
    assert without_image_data(reply)["result"] == {"preview": {"aiify_image": "p.png", "mime_type": "image/png"},
                                                   "data": "kept"}
