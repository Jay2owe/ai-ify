"""Offline, read-only usage guide; imports only the Python standard library."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import difflib
from importlib.resources import files
import json
import re
from typing import Sequence

from . import __version__


@dataclass(frozen=True)
class _Topic:
    title: str
    description: str
    keywords: str = ""
    prerequisites: tuple[str, ...] = ()
    related: tuple[str, ...] = ()


_TOPICS = {
    "overview": _Topic("What ai-ify does", "Orientation and all available guide topics.",
                       "help guide start embed assistant agent chat panel"),
    "messaging": _Topic("Messages between connected assistants", "Named recipients, reply threads and durable message receipts without automatic model turns.",
                         "collaboration communicate assistants messaging mailbox MessageHub peers inbox history send reply audit references", (), ("chat-options", "agent-commands")),
    "setup": _Topic("Install and sign in", "Python extras, Node and npx, subscriptions, where files go.",
                    "install pip extra web node npx subscription login claude codex api key AIIFY_HOME folder"),
    "quickstart": _Topic("Add an assistant to a small app", "A complete runnable example with success checks.",
                         "example tutorial first fastapi mount notes demo", ("setup",),
                         ("actions", "profiles", "page-control", "testing")),
    "actions": _Topic("Offer backend actions", "Functions, registries and dispatchers; read-only, mutating, destructive; approval.",
                      "action registry from_functions from_dispatch from_registry combine destructive mutating approve confirm card",
                      (), ("profiles", "agent-commands", "troubleshooting")),
    "profiles": _Topic("Profiles, instructions and app state", "What each profile may run and what the agent is told.",
                       "profile model effort mode allow deny confirm policy instructions guide state rules When look-only",
                       (), ("actions", "page-control")),
    "context": _Topic("The app's own context, rules and launch buttons", "Context functions, rules on what was typed or the model and effort, and buttons that start the assistant.",
                      "context inject When rule prompt keyword word cost model effort provider Turn Launch launch button data-aiify-launch function registry instructions per-button",
                      (), ("profiles", "page-control")),
    "discovery": _Topic("What the agent finds by itself, and the app map", "Routes as actions, aiify how, and the map the developer builds once.",
                        "discover discovery routes route openapi how question search plain language find app map aiify_map appmap build check README guide topics zero work",
                        (), ("context", "agent-commands")),
    "preparation": _Topic("Prepare and verify app actions during development",
                          "Inspect source, generate backend wrappers and guidance, verify real-app tests, then ship the bundle.",
                          "prepare preparation developer generate wrapper backend workflow CLI-Anything build inspect verify receipt load_prepared",
                          (), ("actions", "discovery", "testing")),
    "chat-options": _Topic("Hooks, suggestions, locked pickers, ask, attachments, notes, queue and schedule", "Everything an app can switch on beyond profiles and context.",
                           "before_send after_reply hook Answer AgentReply suggestions chips starter prompts lock limit picker ask structured json schema pydantic attach attachment file image paste drop notes memory remember queue tab schedule later time",
                           (), ("context", "profiles")),
    "page-control": _Topic("Let the agent use the page", "The panel tag, named UI commands, page state and the control tree.",
                           "panel.js script registerTool setState data-agent off ref tree click fill CSP websocket shadow",
                           (), ("agent-commands", "troubleshooting")),
    "panel-look": _Topic("How the panel looks and where it sits", "inject=True, layouts (side, docked, window, inline), opacity, colours, own launch button.",
                         "layout overlay dock float window inline drag move resize opacity transparent see-through accent colour font launcher inject panel_tag theme",
                         (), ("page-control", "quickstart")),
    "agent-commands": _Topic("The aiify command and its replies", "Commands agents use to drive a running app, and error codes.",
                             "cli aiify apps describe state action.list action.run ui tree ui do wait denied requires_confirmation no_ui stale_ref",
                             (), ("actions", "page-control", "troubleshooting")),
    "console-and-limits": _Topic("Console, usage limits and Codex accounts", "Open the chat in a terminal; limit bars; account switching.",
                                 "console terminal resume usage limit bars weekly 5-hour reset codex-profiles account switch",
                                 (), ("setup", "troubleshooting")),
    "other-apps": _Topic("Apps without a web page, and optional embedding", "Control port only, background start, keeping ai-ify optional.",
                         "qt desktop start_background optional extra environment variable prewarm frozen pyinstaller",
                         (), ("actions", "agent-commands")),
    "evaluate": _Topic("Measure how well the agent does your app's tasks", "Task lists, automatic checks, and runs with and without each discovery helper.",
                       "evaluate evaluation benchmark measure score tasks check pass rate helper mix ablation routes how app map compare provider codex repeats resume report runs.jsonl set_helpers",
                       (), ("discovery", "testing")),
    "testing": _Topic("Test an app that embeds ai-ify", "The scripted fake agent and isolated folders.",
                      "test pytest fake agent AIIFY_ENGINE_COMMAND FAKE_ACP_STORE AIIFY_HOME playwright browser",
                      (), ("quickstart", "agent-commands")),
    "troubleshooting": _Topic("Recognise a problem and check recovery", "Panel, start-up, approvals, error codes, limits.",
                              "error disconnected retrying websocket starting npx approve every command requires_confirmation no_ui stale_ref limit bars picker missing",
                              (), ("setup", "page-control", "agent-commands")),
}


def topics() -> tuple[str, ...]:
    """Return the public topic keys in their documented order."""
    return tuple(_TOPICS)


def _discovery() -> dict:
    return {
        "module": "aiify.context",
        "read": "from aiify import context; print(context.read())",
        "search": "context.search('approval card')",
        "terminal": "python -m aiify.context [topic]",
    }


def _error(message: str, *, topic=None, suggestions: Sequence[str] = ()) -> dict:
    return {"ok": False, "version": __version__, "topic": topic if isinstance(topic, str) else None,
            "error": message, "suggestions": list(suggestions), "available": list(_TOPICS)}


def _body(topic: str) -> str:
    content = files("aiify").joinpath("guide", f"{topic}.md").read_text(encoding="utf-8").strip()
    if topic == "overview":
        content += "\n\n" + "\n".join(
            f"- `{key}` — {item.title}: {item.description}"
            for key, item in _TOPICS.items() if key != "overview"
        )
    return content


def _prerequisites(topic: str) -> list[str]:
    ordered: list[str] = []
    active: set[str] = set()

    def visit(key: str) -> None:
        if key in active:
            raise ValueError(f"Guide prerequisite cycle at {key}")
        if key in ordered:
            return
        active.add(key)
        for dependency in _TOPICS[key].prerequisites:
            visit(dependency)
        active.remove(key)
        ordered.append(key)

    visit(topic)
    return ordered[:-1]


def read(topic: str = "overview", *, format: str = "text") -> str | dict:
    """Read a complete topic with its prerequisites, as text or a JSON-clean dict."""
    if not isinstance(format, str) or format not in ("text", "json"):
        return _error("format must be 'text' or 'json'.", topic=topic)
    if not isinstance(topic, str) or not topic.strip():
        result = _error("topic must be a non-empty string; use 'overview' to start.")
    else:
        topic = topic.strip().casefold()
        if topic not in _TOPICS:
            result = _error(f"Unknown topic {topic!r}. Read 'overview' for the topic index.",
                            topic=topic, suggestions=difflib.get_close_matches(topic, _TOPICS, n=3))
        else:
            item = _TOPICS[topic]
            prerequisites = _prerequisites(topic)
            sections = [f"ai-ify {__version__} — {item.title}"]
            sections.extend(_body(key) for key in [*prerequisites, topic])
            if item.related:
                sections.append("Related topics (read with context.read): " + ", ".join(item.related))
            result = {"ok": True, "version": __version__, "topic": topic, "title": item.title,
                      "content": "\n\n".join(sections), "prerequisites": prerequisites,
                      "related": list(item.related)}
            if topic == "overview":
                result["topics"] = [{"topic": key, "title": entry.title, "description": entry.description}
                                    for key, entry in _TOPICS.items()]
    if format == "json":
        return result
    if result["ok"]:
        return result["content"]
    return result["error"] + "\nAvailable topics: " + ", ".join(result["available"])


_STOP_WORDS = frozenset("a an and are can do for how i in is it my of on or the to use what with".split())


def _words(text: str) -> set[str]:
    return set(re.findall(r"[\w]+", text.casefold())) - _STOP_WORDS


def search(query: str, *, limit: int = 5) -> dict:
    """Search local guide prose, titles and common synonyms without loading data."""
    if not isinstance(query, str) or not query.strip():
        return {**_error("query must be a non-empty string."), "results": []}
    if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
        return {**_error("limit must be a positive integer."), "results": []}
    terms = _words(query)
    matches = []
    for key, item in _TOPICS.items():
        title_hits = terms & _words(key + " " + item.title)
        keyword_hits = terms & _words(item.keywords + " " + item.description)
        body_hits = terms & _words(_body(key))
        matched = title_hits | keyword_hits | body_hits
        if matched:
            score = 5 * len(title_hits) + 3 * len(keyword_hits) + len(body_hits)
            matches.append((score, key, {"topic": key, "title": item.title,
                                        "description": item.description,
                                        "relevance": "Matches: " + ", ".join(sorted(matched))}))
    matches.sort(key=lambda row: (-row[0], row[1]))
    return {"ok": True, "version": __version__, "query": query, "results": [row[2] for row in matches[:limit]],
            "total": len(matches), "truncated": len(matches) > limit}


class _Parser(argparse.ArgumentParser):
    def error(self, message):
        raise ValueError(message)


def _main(argv: Sequence[str] | None = None) -> int:
    parser = _Parser(description="Read the installed ai-ify usage guide.")
    parser.add_argument("topic", nargs="?")
    parser.add_argument("--search", dest="query")
    parser.add_argument("--limit", type=int)
    try:
        args = parser.parse_args(argv)
        if args.query is not None:
            if args.topic is not None:
                raise ValueError("Choose a topic or --search, not both.")
            result = search(args.query, limit=args.limit if args.limit is not None else 5)
        else:
            if args.limit is not None:
                raise ValueError("--limit requires --search.")
            result = read(args.topic if args.topic is not None else "overview", format="json")
    except ValueError as exc:
        result = _error(str(exc))
    print(json.dumps(result, ensure_ascii=True, allow_nan=False))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(_main())
