"""A scripted ACP agent so tests never start npx, Claude or Codex.

Run as ``python -m aiify.testing.fake_agent``. Behaviour depends on the message:
  "permission" -> asks one permission, then says which option came back
  "slow"       -> streams slowly until cancelled
  "history"    -> says how many messages this session has had (resume check)
  "echo"       -> replies with the whole message it received
  "reply-json X" -> replies with X (the rest of that line) in a ```json fence
  "reply-bad"  -> replies with text that is not JSON; "not valid" -> {"fixed": true}
  "/usage"     -> Claude Code's limit report (markdown), like the real local command
  otherwise    -> "hello from fake" in three chunks, one tool call, one usage update
Sessions are kept in the JSON file named by FAKE_ACP_STORE so a new process can
load or resume them.

Signed out: with FAKE_ACP_SIGNIN naming a file, the agent is signed out until that
file exists. It offers a terminal sign-in (``--cli auth login`` prints a link the way
Claude's does and creates the file when given the code LOGIN_CODE) and an agent
sign-in ("chat-gpt").
FAKE_ACP_SIGNIN_AT is "prompt" (like Claude: the chat opens, messages are refused)
or "session" (like Codex: no chat until signed in).
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import uuid
from pathlib import Path

import acp
from acp import schema, start_tool_call, update_agent_message_text, update_tool_call

STORE = Path(os.environ.get("FAKE_ACP_STORE", "fake_acp_sessions.json"))      # where sessions persist
CAPS = os.environ.get("FAKE_ACP_CAPS", "resume,load")
SIGNIN = os.environ.get("FAKE_ACP_SIGNIN")
SIGNIN_AT = os.environ.get("FAKE_ACP_SIGNIN_AT", "prompt")


def signed_in() -> bool:
    return not SIGNIN or Path(SIGNIN).exists()


def _need_signin(at: str) -> None:
    if SIGNIN_AT == at and not signed_in():
        raise acp.RequestError.auth_required()


def _load() -> dict:
    try:
        return json.loads(STORE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _save(data: dict) -> None:
    STORE.write_text(json.dumps(data), encoding="utf-8")


def _options(values: dict) -> list:
    def select(cid, name, choices):
        return schema.SessionConfigOptionSelect(
            id=cid, name=name, type="select", current_value=values[cid],
            options=[schema.SessionConfigSelectOption(value=c, name=c.title()) for c in choices])
    return [select("model", "Model", ["fast", "smart"]),
            select("effort", "Effort", ["default", "low", "high"]),
            select("mode", "Mode", ["default", "plan"])]


DEFAULTS = {"model": "fast", "effort": "default", "mode": "default"}
USAGE_REPORT = """### Limits

**5-hour limit** — **14%** · Resets Oct 1, 5:39 PM GMT+1

`███░░░░░░░░░░░░░░░░░`

**Weekly · all models** — **92%** · Resets Oct 4, 5:59 AM GMT+1

`██████████████████░░`
"""


class FakeAgent:
    def __init__(self):
        self.conn = None
        self.cancelled: set[str] = set()

    def on_connect(self, conn):
        self.conn = conn

    async def initialize(self, protocol_version, client_capabilities=None, client_info=None, **kw):
        caps = CAPS.split(",")
        return schema.InitializeResponse(
            protocol_version=protocol_version,
            agent_capabilities=schema.AgentCapabilities(
                load_session="load" in caps,
                session_capabilities=schema.SessionCapabilities(
                    resume={} if "resume" in caps else None)),
            agent_info=schema.Implementation(name="fake", version="1"),
            auth_methods=[schema.TerminalAuthMethod(id="claude-ai-login", name="Claude Subscription",
                                                    args=["--cli", "auth", "login"], type="terminal"),
                          schema.AuthMethodAgent(id="chat-gpt", name="ChatGPT")] if SIGNIN else None)

    async def authenticate(self, method_id, **kw):
        if method_id == "chat-gpt":
            Path(SIGNIN).write_text("signed in", encoding="utf-8")
        return schema.AuthenticateResponse()

    async def new_session(self, cwd, **kw):
        _need_signin("session")
        sid = uuid.uuid4().hex
        data = _load()
        data[sid] = {"values": dict(DEFAULTS), "turns": 0}
        _save(data)
        return schema.NewSessionResponse(session_id=sid, config_options=_options(DEFAULTS))

    def _existing(self, sid):
        data = _load()
        if sid not in data:
            raise acp.RequestError.invalid_params({"session": "unknown"})
        return data[sid]

    async def load_session(self, cwd, session_id, **kw):
        s = self._existing(session_id)
        return schema.LoadSessionResponse(config_options=_options(s["values"]))

    async def resume_session(self, session_id, cwd, **kw):
        s = self._existing(session_id)
        return schema.ResumeSessionResponse(config_options=_options(s["values"]))

    async def set_config_option(self, config_id, session_id, value, **kw):
        data = _load()
        data[session_id]["values"][config_id] = value
        _save(data)
        return schema.SetSessionConfigOptionResponse(config_options=_options(data[session_id]["values"]))

    async def cancel(self, session_id, **kw):
        self.cancelled.add(session_id)

    async def say(self, sid, text):
        await self.conn.session_update(sid, update_agent_message_text(text))

    async def prompt(self, session_id, prompt, **kw):
        _need_signin("prompt")
        text = "".join(getattr(b, "text", "") for b in prompt)
        data = _load()
        data[session_id]["turns"] += 1
        _save(data)
        self.cancelled.discard(session_id)
        low = text.lower()
        if text.strip() == "/usage":
            await self.say(session_id, USAGE_REPORT)
        elif "reply-json " in low:                       # the JSON after it, in a code fence
            await self.say(session_id, "```json\n" + text.split("reply-json ", 1)[1].splitlines()[0] + "\n```")
        elif "reply-bad" in low:
            await self.say(session_id, "not json at all")
        elif "not valid" in low:
            await self.say(session_id, '{"fixed": true}')
        elif "permission" in low:
            tc = schema.ToolCallUpdate(tool_call_id="t1", title="delete things",
                                       raw_input={"command": "rm -rf stuff"})
            options = [schema.PermissionOption(option_id="yes", name="Yes", kind="allow_once"),
                       schema.PermissionOption(option_id="no", name="No", kind="reject_once")]
            resp = await self.conn.request_permission(session_id=session_id, tool_call=tc, options=options)
            out = resp.outcome
            await self.say(session_id, f"outcome={getattr(out, 'option_id', None) or 'cancelled'}")
        elif "slow" in low:
            for i in range(200):
                if session_id in self.cancelled:
                    return schema.PromptResponse(stop_reason="cancelled")
                await self.say(session_id, f"{i} ")
                await asyncio.sleep(0.05)
        elif "history" in low:
            await self.say(session_id, f"turns={data[session_id]['turns']}")
        elif "echo" in low:
            await self.say(session_id, text)
        else:
            for chunk in ("hello ", "from ", "fake"):
                await self.say(session_id, chunk)
            await self.conn.session_update(session_id, start_tool_call(
                "t2", "list files", kind="execute", status="in_progress", raw_input={"command": "dir"}))
            await self.conn.session_update(session_id, update_tool_call(
                "t2", status="completed", raw_output={"stdout": "a.csv"}))
            await self.conn.session_update(session_id, schema.UsageUpdate(
                session_update="usage_update", used=10, size=100,
                field_meta={"_claude/rateLimit": {"status": "allowed", "utilization": 0.2,
                                                  "rateLimitType": "five_hour", "resetsAt": 4102444800}}))
        return schema.PromptResponse(stop_reason="end_turn")


LOGIN_LINK = "https://example.test/oauth/authorize?code=true&state=abc"
LOGIN_CODE = "GOODCODE"


def cli(args: list[str]) -> int:
    """The bundled-CLI stand-in for ``--cli auth login``: link, then wait for the code."""
    if args[:2] != ["auth", "login"]:
        return 2
    sys.stdout.write("Opening browser to sign in...\nIf the browser didn't open, visit: "
                     f"\x1b]8;;{LOGIN_LINK}\x1b\\{LOGIN_LINK}\x1b]8;;\x1b\\\n"
                     "Paste code here if prompted > ")
    sys.stdout.flush()
    if sys.stdin.readline().strip() != LOGIN_CODE:
        print("Invalid code")
        return 1
    Path(SIGNIN).write_text("signed in", encoding="utf-8")
    print("Login successful.")
    return 0


def main() -> None:
    if "--cli" in sys.argv:
        sys.exit(cli(sys.argv[sys.argv.index("--cli") + 1:]))
    asyncio.run(acp.run_agent(FakeAgent(), use_unstable_protocol=True))   # resume is "unstable" in SDK 0.12


if __name__ == "__main__":
    main()
