# Embed ai-ify in another application

Think of ai-ify as a chat window connected to the tools your app already has.
Keep the app's calculations and storage in its own functions; supply those
functions and the instructions needed to use them.

## Choose the integration

| Your app | Use | Read next |
|---|---|---|
| FastAPI web app that needs an assistant | `Agent` and `agent.mount(app)` | `quickstart` |
| App that already runs agents and owns their conversations | Shared panel assets and `aiify.bindHost` | `host-runner` |
| Desktop or other non-web app | `Agent.start_background()` for a local control port | `other-apps` |

The shared-panel integration retains your existing runner and approval rules.
The background control port provides callable actions; it does not add a
desktop chat panel.

Read `features` for the full catalogue and constructor options, `best-practices`
for a complete configurable recipe, and `programmatic` for lifecycle/events and
structured questions. The example below is intentionally the smallest integration.

## Connect a FastAPI app

Install `ai-ify[web]` in the host app's Python environment. This complete
example uses the shipped fake agent, so verification needs no subscription,
Node installation or real model request. Save it as `example_app.py`, then run
`python example_app.py`.

```python
import sys

from fastapi import FastAPI
from fastapi.responses import HTMLResponse

from aiify import Agent
from aiify.actions import from_functions

notes = []

def add_note(text: str):
    """Add a text note to this session."""
    notes.append(text)
    return {"count": len(notes)}

def list_notes():
    """Read the notes in this session."""
    return {"notes": list(notes)}

app = FastAPI()

@app.get("/", response_class=HTMLResponse)
def page():
    return '<h1>Notes</h1><script src="/aiify/panel.js" defer></script>'

agent = Agent(
    "example-notes",
    actions=from_functions(
        {"notes.add": add_note, "notes.list": list_notes},
        mutating=["notes.add"],
    ),
    guide="Notes are text and last only until this app stops.",
    state=lambda: {"note_count": len(notes)},
    engine_argv={"claude": [sys.executable, "-m", "aiify.testing.fake_agent"]},
)
agent.mount(app)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8770)
```

In an existing app, reuse its `FastAPI` instance, add the script tag to its
served page, and mount after registering its routes and middleware. Mount once;
the host's server lifecycle starts and stops the assistant. Keep your current
server launch command. Alternatively, `agent.mount(app, inject=True)` adds the
panel tag to HTML responses automatically; choose one inclusion method.

## Verify before switching to a real agent

Use a temporary `AIIFY_HOME` folder during checks; see `testing` for isolation.
With the example server running:

1. Open `http://127.0.0.1:8770/`, open the AI panel and send `hi`.
   The fake answers `hello from fake`.
2. Run `aiify --app example-notes action.run notes.add text=hello`.
   Expect `ok: true` and a result with `count: 1`.
3. Run `aiify --app example-notes action.run notes.list`.
   Expect a result containing `notes: ["hello"]`.
4. Stop the server. Its control-port registration should disappear from
   `aiify apps`.

The fake verifies wiring and message delivery; it does not interpret natural
language requests to choose actions. Remove `engine_argv` to use the default
Claude adapter, then follow `setup` for Node and subscription sign-in. Read
`profiles` to select Codex or configure permitted operations.

## Adapt the connection to your backend

- Use `from_functions` for plain callables and explicitly mark writes with
  `mutating`; mark deletes and overwrites with `destructive` so approval is
  required. Read `actions` for existing registries and dispatchers.
- Forward the app's existing defaults. Do not replace calculation settings
  merely to expose them to the assistant.
- Supply `guide` for task instructions and `state` for current app facts.
  Read `context` for conditional instructions and launch buttons.
- Read `page-control` when the assistant must switch views or use controls.
- Guidance search is on, shipped app maps are auto-discovered, web-route
  actions are off, and prepared action bundles are absent by default. Read
  `discovery` and `preparation` before enabling those integrations.

This example stores notes in memory: restarting loses them. A real integration
should call the host's storage functions. For GUI libraries, arrange calls on
the required UI thread; a background control port does not make widgets safe
to access from other threads.
