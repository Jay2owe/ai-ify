"""The running app's operations as MCP tools, for an assistant with no shell or files.

``Agent(access="app")`` starts this for each conversation instead of teaching the
agent the ``aiify`` command:

    python -m aiify.tool_server --app NAME@PID

It speaks the Model Context Protocol over stdin/stdout (one JSON-RPC message per
line) and forwards each tool call to the app's control port, exactly as the
``aiify`` command would. Only the operations the app answers are listed.
"""
from __future__ import annotations

import json
import sys

from . import __version__
from .cli import pick_app, send
from .control_port import list_apps
from .protocol import IMAGE_KEY, IMAGE_TYPES, without_image_data

PROTOCOLS = ("2025-11-25", "2025-06-18", "2025-03-26", "2024-11-05")
TIMEOUT = 1800.0                 # an action may render or generate for minutes
MAX_IMAGES = 6

_TEXT = {"type": "string"}
_OBJECT = {"type": "object", "additionalProperties": True}
_CONFIRM = {"type": "boolean", "description": "true only after the person agreed to a step that "
                                              "answered requires_confirmation"}


def _schema(properties: dict | None = None, required: tuple = ()) -> dict:
    return {"type": "object", "properties": properties or {}, "required": list(required),
            "additionalProperties": False}


# tool name -> (control-port op, description, input schema)
TOOLS = {
    "app_describe": ("describe", "What the app offers right now: its operations, on-screen commands and guide.",
                     _schema()),
    "app_state": ("state", "What is on screen and selected in the app now.", _schema()),
    "action_list": ("action.list", "List the app's backend actions (prefer these). `match` filters names, "
                    "e.g. drawing.*", _schema({"match": _TEXT})),
    "action_describe": ("action.describe", "One action's parameters and what it does.",
                        _schema({"name": _TEXT}, ("name",))),
    "action_run": ("action.run", "Run one backend action with its parameters as a JSON object (nested "
                   "objects, arrays and SVG text are fine). A reply with code requires_confirmation needs "
                   "the person's approval: describe the step, ask them, and only after they agree call "
                   "again with confirm=true. code denied means you are not allowed that step.",
                   _schema({"name": _TEXT, "params": _OBJECT, "confirm": _CONFIRM}, ("name",))),
    "how": ("how", "Ask the app how to do something: it searches its actions, screens, guide and map.",
            _schema({"q": {"type": "string", "description": "the question in plain words"}}, ("q",))),
    "ui_do": ("ui.do", "Run a named on-screen command the page offers (listed by app_describe).",
              _schema({"name": _TEXT, "params": _OBJECT, "confirm": _CONFIRM}, ("name",))),
    "ui_tree": ("ui.tree", "The controls on screen, with refs like e12 (refs go stale after a change).",
                _schema()),
    "ui_click": ("ui.click", "Click one control by its ref from ui_tree.", _schema({"target": _TEXT}, ("target",))),
    "ui_fill": ("ui.fill", "Type text into one control.", _schema({"target": _TEXT, "value": _TEXT},
                                                                ("target", "value"))),
    "ui_select": ("ui.select", "Choose a value in one control.", _schema({"target": _TEXT, "value": {}},
                                                                      ("target", "value"))),
    "ui_scroll": ("ui.scroll", "Scroll the page or one control.", _schema({"target": _TEXT, "direction": _TEXT})),
    "ui_read": ("ui.read", "Read one control's text and value.", _schema({"target": _TEXT}, ("target",))),
    "notes_read": ("notes.read", "Read the notes kept for this app across chats.", _schema()),
    "notes_add": ("notes.add", "Save one short line to the app's notes (something to remember, or a lasting "
                  "preference).", _schema({"text": _TEXT}, ("text",))),
    "messages_peers": ("messages.peers", "List the other assistants you can message.", _schema()),
    "messages_inbox": ("messages.inbox", "Read received messages; reading does not acknowledge them.",
                       _schema({"after": _TEXT, "limit": {"type": "integer"}, "unread": {"type": "boolean"}})),
    "messages_history": ("messages.history", "Read sent and received messages.",
                         _schema({"after": _TEXT, "limit": {"type": "integer"}})),
    "messages_send": ("messages.send", "Send a message to another assistant; it does not start their reply.",
                      _schema({"recipient": _TEXT, "text": _TEXT, "references": {"type": "array"},
                               "reply_to": _TEXT, "request_key": _TEXT}, ("recipient", "text"))),
    "messages_reply": ("messages.reply", "Reply to a received message in its thread.",
                       _schema({"message_id": _TEXT, "text": _TEXT, "references": {"type": "array"},
                                "request_key": _TEXT}, ("message_id", "text"))),
    "messages_ack": ("messages.ack", "Record that received messages were dealt with.",
                     _schema({"message_ids": {"type": "array", "items": _TEXT}}, ("message_ids",))),
}


def _images(value) -> list[dict]:
    """The images an action returned as :class:`aiify.ImageFile`, already read by the app.

    Only data the app packed is sent; a path alone is never opened here, so an action
    that echoes its input cannot be used to read a file."""
    if isinstance(value, dict):
        if isinstance(value.get(IMAGE_KEY), str) and isinstance(value.get("data"), str) \
                and value.get("mime_type") in IMAGE_TYPES.values():
            return [value]
        return [i for v in value.values() for i in _images(v)]
    if isinstance(value, list):
        return [i for v in value for i in _images(v)]
    return []


class Server:
    def __init__(self, app: str | None):
        self.app = app

    def _target(self) -> dict:
        return pick_app(list_apps(), self.app)

    def request(self, op: str, fields: dict) -> dict:
        try:
            info = self._target()
        except LookupError as exc:
            return {"ok": False, "code": "no_app", "error": str(exc)}
        try:
            return send(info, {"op": op, **fields}, timeout=TIMEOUT)
        except OSError as exc:
            return {"ok": False, "code": "failed", "error": f"could not reach {info.get('app')}: {exc}"}

    def tools(self) -> list[dict]:
        reply = self.request("describe", {})
        ops = set((reply.get("result") or {}).get("ops") or ()) if reply.get("ok") else set()
        return [{"name": name, "description": text, "inputSchema": schema}
                for name, (op, text, schema) in TOOLS.items() if not ops or op in ops or op == "describe"]

    def call(self, name: str, arguments: dict) -> dict:
        if name not in TOOLS:
            return {"content": [{"type": "text", "text": f"unknown tool {name}"}], "isError": True}
        op = TOOLS[name][0]
        reply = self.request(op, {k: v for k, v in (arguments or {}).items() if v is not None})
        images = [{"type": "image", "data": i["data"], "mimeType": i["mime_type"]}
                  for i in _images(reply.get("result"))][:MAX_IMAGES]
        return {"content": [{"type": "text", "text": json.dumps(without_image_data(reply), ensure_ascii=False)},
                            *images],
                "isError": not reply.get("ok")}

    def handle(self, message: dict) -> dict | None:
        method, mid = message.get("method"), message.get("id")
        if mid is None:                                   # a notification
            return None
        params = message.get("params") or {}
        if method == "initialize":
            asked = params.get("protocolVersion")
            result = {"protocolVersion": asked if asked in PROTOCOLS else PROTOCOLS[1],
                      "capabilities": {"tools": {"listChanged": False}},
                      "serverInfo": {"name": "aiify-app", "version": __version__}}
        elif method == "ping":
            result = {}
        elif method == "tools/list":
            result = {"tools": self.tools()}
        elif method == "tools/call":
            result = self.call(params.get("name"), params.get("arguments") or {})
        else:
            return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": f"no method {method}"}}
        return {"jsonrpc": "2.0", "id": mid, "result": result}

    def serve(self, stdin=None, stdout=None) -> None:
        stdin = stdin or sys.stdin
        stdout = stdout or sys.stdout
        for line in stdin:
            if not line.strip():
                continue
            try:
                message = json.loads(line)
            except ValueError:
                reply = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "not JSON"}}
            else:
                reply = self.handle(message) if isinstance(message, dict) else None
            if reply is not None:
                stdout.write(json.dumps(reply, ensure_ascii=False) + "\n")
                stdout.flush()


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    app = args[args.index("--app") + 1] if "--app" in args[:-1] else None
    sys.stdin.reconfigure(encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8")
    Server(app).serve()
    return 0


if __name__ == "__main__":
    sys.exit(main())
