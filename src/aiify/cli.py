"""``aiify``: talk to a running app that has ai-ify embedded.

    aiify apps
    aiify [--app NAME] ping | describe | state
    aiify [--app NAME] action.list [match=plot.*]
    aiify [--app NAME] action.run NAME key=value ... [--confirm]
    aiify [--app NAME] ui tree | ui click REF | ui fill REF VALUE | ui do NAME key=value ...
    aiify [--app NAME] how "plain question"
    aiify [--app NAME] raw '{"op": "state"}'

Prints the reply as JSON. Exit status 0 when ok, 1 otherwise. The message
format is in docs/protocol.md.
"""
from __future__ import annotations

import json
import socket
import sys
from pathlib import Path

from .control_port import list_apps
from .protocol import PROTOCOL_VERSION, dumps

TARGET_OPS = {"ui.click", "ui.fill", "ui.select", "ui.scroll", "ui.read", "screenshot"}
NAME_OPS = {"action.run", "action.describe", "ui.do"}
PARAM_OPS = {"action.run", "ui.do"}
GROUPS = {"ui", "action"}


def _unshell(text: str) -> str:
    """Undo bash-style quoting typed into PowerShell: ``key=\\"abc\\"`` arrives as
    ``\\"abc\\"`` or ``\\abc\\``. Only a value wrapped at both ends and with no
    other backslash is touched, so a real Windows path keeps its backslashes."""
    for left, right in (('\\"', '\\"'), ("\\", "\\")):
        if len(text) > len(left) + len(right) and text.startswith(left) and text.endswith(right):
            inner = text[len(left):-len(right)]
            if "\\" not in inner:
                return inner
    return text


def _value(text: str):
    text = _unshell(text)
    try:
        return json.loads(text)
    except ValueError:
        return text


def build_request(words: list[str], *, confirm: bool = False) -> dict:
    """Turn command words into a request dict (without token)."""
    if not words:
        raise ValueError("no operation given")
    op, rest = words[0], words[1:]
    if op in GROUPS:
        if not rest:
            raise ValueError(f"'{op}' needs a sub-command, e.g. '{op} {'tree' if op == 'ui' else 'list'}'")
        op, rest = f"{op}.{rest[0]}", rest[1:]
    if op == "raw":
        if len(rest) != 1:
            raise ValueError("raw takes one JSON object")
        req = json.loads(rest[0])
        if not isinstance(req, dict):
            raise ValueError("raw takes one JSON object")
        return req
    if op == "how":
        if not rest:
            raise ValueError('how needs a question, e.g. how "export the summary"')
        return {"op": "how", "q": " ".join(rest)}
    req: dict = {"op": op}
    bare, pairs = [], {}
    for word in rest:
        key, sep, value = word.partition("=")
        if sep and key and key.replace("_", "").replace("-", "").isalnum():
            pairs[key] = _value(value)
        else:
            bare.append(word)
    if bare:
        if op in NAME_OPS:
            req["name"] = bare.pop(0)
        elif op in TARGET_OPS:
            req["target"] = bare.pop(0)
    if bare and op in ("ui.fill", "ui.select"):
        req["value"] = _value(bare.pop(0)) if op == "ui.select" else bare.pop(0)
    if bare:
        raise ValueError(f"unexpected argument(s) for {op}: {' '.join(bare)}")
    if op in PARAM_OPS:
        req["params"] = pairs
    else:
        req.update(pairs)
    if confirm:
        req["confirm"] = True
    return req


def pick_app(apps: list[dict], name: str | None) -> dict:
    """``name``, a prefix of it, or ``name@pid`` for one running copy of the app (an
    embedded agent always names its own copy, so two open copies are not confused)."""
    if name and "@" in name and name.rsplit("@", 1)[1].isdigit():
        base, pid = name.rsplit("@", 1)
        hit = [a for a in apps if a.get("app") == base and str(a.get("pid")) == pid]
        if hit:
            return hit[0]
        raise LookupError(f"no running app called {base!r} with pid {pid}; running: {_names(apps) or 'none'}")
    if name:
        exact = [a for a in apps if a.get("app") == name]
        prefix = exact or [a for a in apps if str(a.get("app", "")).startswith(name)]
        if len(prefix) == 1:
            return prefix[0]
        if not prefix:
            raise LookupError(f"no running app called {name!r}; running: {_names(apps) or 'none'}")
        raise LookupError(f"{len(prefix)} apps match {name!r}: {_names(prefix)}")
    if len(apps) == 1:
        return apps[0]
    if not apps:
        raise LookupError("no app with ai-ify is running")
    raise LookupError(f"several apps are running ({_names(apps)}); pass --app NAME")


def _names(apps: list[dict]) -> str:
    return ", ".join(f"{a.get('app')} (pid {a.get('pid')})" for a in apps)


def send(info: dict, request: dict, timeout: float = 120.0) -> dict:
    request = {"protocol": PROTOCOL_VERSION, "token": info["token"], "id": 1, **request}
    with socket.create_connection(("127.0.0.1", int(info["port"])), timeout=timeout) as sock:
        sock.sendall((dumps(request) + "\n").encode("utf-8"))
        data = b""
        while not data.endswith(b"\n"):
            chunk = sock.recv(1 << 16)
            if not chunk:
                break
            data += chunk
    if not data:
        return {"ok": False, "code": "failed", "error": "the app closed the connection without a reply"}
    return json.loads(data)


def main(argv: list[str] | None = None, *, directory: Path | None = None, out=None) -> int:
    out = out or sys.stdout
    args = list(sys.argv[1:] if argv is None else argv)
    if not args or args[0] in ("-h", "--help", "help"):
        out.write(__doc__ + "\n")
        return 0 if args else 2
    app_name = None
    confirm = False
    timeout = 120.0
    words = []
    i = 0
    while i < len(args):
        a = args[i]
        if a == "--app" and i + 1 < len(args):
            app_name = args[i + 1]
            i += 2
            continue
        if a.startswith("--app="):
            app_name = a.split("=", 1)[1]
        elif a == "--confirm":
            confirm = True
        elif a.startswith("--timeout="):
            timeout = float(a.split("=", 1)[1])
        else:
            words.append(a)
        i += 1

    def emit(obj) -> None:
        out.write(json.dumps(obj, indent=1, ensure_ascii=False) + "\n")

    apps = list_apps(directory)
    if words[:1] == ["apps"]:
        emit({"ok": True, "result": [{k: a[k] for k in ("app", "pid", "port", "started") if k in a}
                                     for a in apps]})
        return 0
    try:
        request = build_request(words, confirm=confirm)
        info = pick_app(apps, app_name)
    except (ValueError, LookupError) as exc:
        emit({"ok": False, "code": "invalid", "error": str(exc)})
        return 1
    try:
        reply = send(info, request, timeout=timeout)
    except OSError as exc:
        emit({"ok": False, "code": "failed", "error": f"could not reach {info.get('app')}: {exc}"})
        return 1
    emit(reply)
    return 0 if reply.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
