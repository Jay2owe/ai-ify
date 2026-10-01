# ai-ify

Embed an AI agent inside any app. The person chats with it in a panel inside
the app (or opens a console on the same conversation); the agent runs on the
Claude or Codex subscription already logged in on the machine, and controls the
app only in the ways the app's developer allows: backend actions, named UI
commands, and an automatic tree of the page's controls.

## Install

```bash
pip install "ai-ify[web]"     # chat panel for FastAPI apps
pip install ai-ify            # control port and the aiify command only
```

Also needed: Node.js with `npx` (the first chat downloads the agent adapter, which
brings its own copy of Claude Code or Codex), and a Claude or ChatGPT subscription.
People who are not signed in get a "Sign in" card in the panel. No API key is used.

## Use

```python
from aiify import Agent, Profile
from aiify.actions import from_functions

agent = Agent(
    app="myapp",
    actions=from_functions({"notes.add": add_note, "notes.clear": clear_notes},
                           destructive=["notes.clear"]),
    profiles={"default": Profile(provider="claude")},
)
agent.mount(fastapi_app)          # chat panel + websocket + local control port
```

and in the page:

```html
<script src="/aiify/panel.js" defer></script>
```

The app can add its own context: rules on what the person typed or the model in use
(`When(prompt="cost", add_instructions=price_note)`), and buttons that start the
assistant with their own set-up (`launches={"explain": Launch(...)}`, then
`<button data-aiify-launch="explain">`). See `python -m aiify.context context`.
Hooks before and after each message, suggested prompts, locked pickers, one-off
questions from code (`await agent.ask(...)`), attachments, app notes, and queued or
scheduled messages are each one switch: `python -m aiify.context chat-options`.

With no extra code the agent also finds the app's web routes and docs, and answers
"how do I..." with `aiify how`. Developers can add an app map, written once by their
own agent from the source: `python -m aiify.appmap build myapp.main:app`. See
`python -m aiify.context discovery`.

Destructive actions show a "Run it?" card before they run. Agents (the embedded
one, or any other on the machine) reach the running app with the `aiify` command:
`aiify apps`, `aiify --app myapp action.list`, `aiify --app myapp ui tree`.

## Documentation

- Usage guide, shipped with the package: `python -m aiify.context [topic]`, or
  `from aiify import context; print(context.read())`. Also as
  [README_AI.md](https://github.com/Jay2owe/ai-ify/blob/main/README_AI.md).
- [Embedding guide](https://github.com/Jay2owe/ai-ify/blob/main/docs/embedding-guide.md),
  with Circadian Workbench as the worked example.
- [Message format](https://github.com/Jay2owe/ai-ify/blob/main/docs/protocol.md).

## Development

```bash
python -m venv .venv
.venv/bin/python -m pip install -e ".[web,test]"     # Windows: .venv\Scripts\python.exe
.venv/bin/python -m pytest -m "not browser"          # browser tests need Edge or Playwright's Chromium
```

Releases are published by GitHub Actions when a `vX.Y.Z` tag matching the
package version is pushed ([RELEASING.md](https://github.com/Jay2owe/ai-ify/blob/main/RELEASING.md)).

Install name `ai-ify`, import name `aiify`. MIT licence. The bundled
`page-controller` (Alibaba, MIT) builds the page control tree.
