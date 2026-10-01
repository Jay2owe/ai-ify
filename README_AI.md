# aiify agent guide

Package version: `0.2.0`

Read-only usage guide generated from the package's public context module.

Structured companion: `aiify_context.json`.

## Reader

```python
from aiify import context; context.read(format='json')
```

## What ai-ify does (`overview`)

````markdown
ai-ify 0.2.0 — What ai-ify does

ai-ify puts an AI agent inside an app. The person chats with it in a panel on
the app's page, or opens the same conversation in a terminal. The agent runs on
the Claude or Codex subscription already signed in on the computer (no API key),
and can change the app only in the ways its developer allows:

1. Backend actions: Python functions the app exposes, each marked as
   read-only, changing data, or destructive. Destructive ones ask the person first.
2. Named UI commands: page functions registered with `window.aiify.registerTool`,
   such as "switch to the plots view".
3. The control tree: every visible button, field and menu on the page, so the
   agent can click or fill controls nobody named in advance.

The agent reaches the running app through a local control port with the `aiify`
command (`aiify action.list`, `aiify ui tree`). The app decides which profiles the
person can pick, what each may run, and what extra instructions apply in which state.

Minimal use in a FastAPI app:

```python
from aiify import Agent, Profile
agent = Agent(app="myapp", actions={"notes.add": add_note},
              profiles={"default": Profile(provider="claude")})
agent.mount(fastapi_app)      # then add <script src="/aiify/panel.js" defer></script> to the page
```

Read a topic with `context.read("<topic>")`; search with `context.search("<words>")`.

Topics:

- `setup` — Install and sign in: Python extras, Node and npx, subscriptions, where files go.
- `quickstart` — Add an assistant to a small app: A complete runnable example with success checks.
- `actions` — Offer backend actions: Functions, registries and dispatchers; read-only, mutating, destructive; approval.
- `profiles` — Profiles, instructions and app state: What each profile may run and what the agent is told.
- `context` — The app's own context, rules and launch buttons: Context functions, rules on what was typed or the model and effort, and buttons that start the assistant.
- `discovery` — What the agent finds by itself, and the app map: Routes as actions, aiify how, and the map the developer builds once.
- `chat-options` — Hooks, suggestions, locked pickers, ask, attachments, notes, queue and schedule: Everything an app can switch on beyond profiles and context.
- `page-control` — Let the agent use the page: The panel tag, named UI commands, page state and the control tree.
- `panel-look` — How the panel looks and where it sits: inject=True, layouts (side, docked, window, inline), opacity, colours, own launch button.
- `agent-commands` — The aiify command and its replies: Commands agents use to drive a running app, and error codes.
- `console-and-limits` — Console, usage limits and Codex accounts: Open the chat in a terminal; limit bars; account switching.
- `other-apps` — Apps without a web page, and optional embedding: Control port only, background start, keeping ai-ify optional.
- `testing` — Test an app that embeds ai-ify: The scripted fake agent and isolated folders.
- `troubleshooting` — Recognise a problem and check recovery: Panel, start-up, approvals, error codes, limits.
````

## Install and sign in (`setup`)

```markdown
ai-ify 0.2.0 — Install and sign in

## What has to be installed

- Python 3.10 or newer. `pip install "ai-ify[web]"` for the chat panel (FastAPI,
  uvicorn and a websocket library); plain `pip install ai-ify` gives the control
  port and the `aiify` command only.
- Node.js with `npx` on the PATH. The first chat downloads the agent adapter
  (`@agentclientprotocol/claude-agent-acp` or `@agentclientprotocol/codex-acp`);
  later starts reuse npm's cache. Each adapter brings its own copy of Claude Code or
  Codex, so neither CLI nor any desktop app has to be installed.
- A Claude or ChatGPT subscription. An existing login (`claude`, or `codex login`) is
  used as it is; otherwise the panel shows a "Sign in" card the first time. ai-ify
  never asks for an API key.
- Optional: `codex-profiles` (npm) if several Codex accounts are saved; the panel
  then offers an account picker.

## Where ai-ify keeps files

Everything goes in one per-user folder, never in the app's own folder:
`%LOCALAPPDATA%\ai-ify` on Windows, `~/.local/share/ai-ify` elsewhere, or the
folder named by the `AIIFY_HOME` environment variable.

- `apps/`: one small file per running app (its port and a random token), removed
  when the app stops. The `aiify` command reads these to find apps.
- `work/<app>/`: the agent's working folder for that app. The agent starts there,
  not in the app's data folder.

## Safety defaults

- The control port listens on 127.0.0.1 only and needs the token from the app's file.
- The panel's web routes accept only same-origin requests carrying an `X-Aiify: 1` header.
- Importing `aiify` starts nothing; an agent process starts only when a panel opens
  (or the app asks for it) and stops with the app.
```

## Add an assistant to a small app (`quickstart`)

````markdown
ai-ify 0.2.0 — Add an assistant to a small app

## What has to be installed

- Python 3.10 or newer. `pip install "ai-ify[web]"` for the chat panel (FastAPI,
  uvicorn and a websocket library); plain `pip install ai-ify` gives the control
  port and the `aiify` command only.
- Node.js with `npx` on the PATH. The first chat downloads the agent adapter
  (`@agentclientprotocol/claude-agent-acp` or `@agentclientprotocol/codex-acp`);
  later starts reuse npm's cache. Each adapter brings its own copy of Claude Code or
  Codex, so neither CLI nor any desktop app has to be installed.
- A Claude or ChatGPT subscription. An existing login (`claude`, or `codex login`) is
  used as it is; otherwise the panel shows a "Sign in" card the first time. ai-ify
  never asks for an API key.
- Optional: `codex-profiles` (npm) if several Codex accounts are saved; the panel
  then offers an account picker.

## Where ai-ify keeps files

Everything goes in one per-user folder, never in the app's own folder:
`%LOCALAPPDATA%\ai-ify` on Windows, `~/.local/share/ai-ify` elsewhere, or the
folder named by the `AIIFY_HOME` environment variable.

- `apps/`: one small file per running app (its port and a random token), removed
  when the app stops. The `aiify` command reads these to find apps.
- `work/<app>/`: the agent's working folder for that app. The agent starts there,
  not in the app's data folder.

## Safety defaults

- The control port listens on 127.0.0.1 only and needs the token from the app's file.
- The panel's web routes accept only same-origin requests carrying an `X-Aiify: 1` header.
- Importing `aiify` starts nothing; an agent process starts only when a panel opens
  (or the app asks for it) and stops with the app.

## A notes app with an assistant, in one file

This example runs without any subscription: `engine_argv` swaps the real agent
for ai-ify's scripted test agent. Remove that line to use Claude.

```python
# notes_app.py  -  pip install "ai-ify[web]"; python notes_app.py
import sys
import uvicorn
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from aiify import Agent, Profile
from aiify.actions import from_functions

NOTES = []

def add_note(text: str):
    """Add a note."""
    NOTES.append(text)
    return {"count": len(NOTES)}

def clear_notes():
    """Delete every note."""
    NOTES.clear()
    return "cleared"

fake = [sys.executable, "-m", "aiify.testing.fake_agent"]
agent = Agent(
    app="notes",
    actions=from_functions({"notes.add": add_note, "notes.clear": clear_notes},
                           destructive=["notes.clear"], mutating=["notes.add"]),
    guide="A list of short text notes.",
    profiles={"default": Profile(provider="claude")},
    state=lambda: {"notes": NOTES},
    engine_argv={"claude": fake},          # remove to use the real Claude
)
app = FastAPI()

@app.get("/", response_class=HTMLResponse)
def page():
    return '<h1>Notes</h1><script src="/aiify/panel.js" defer></script>'

agent.mount(app)
uvicorn.run(app, host="127.0.0.1", port=8770)
```

## Check that it works

1. Open http://127.0.0.1:8770/ and click the round "AI" button: the panel opens
   and its status line reads "ready". Type "hi": the scripted agent answers
   "hello from fake".
2. In a second terminal: `aiify --app notes action.run notes.add text=hello`
   prints `{"ok": true, ... "result": {"count": 1}}`.
3. `aiify --app notes action.run notes.clear` with the panel open shows a
   "Run notes.clear?" card in the panel; "Don't" makes the command print
   `"code": "denied"`. With no panel open it prints `"code": "requires_confirmation"`.

The real agent does the same through these commands when the person asks it to.

Related topics (read with context.read): actions, profiles, page-control, testing
````

## Offer backend actions (`actions`)

```markdown
ai-ify 0.2.0 — Offer backend actions

## Backend actions: what the agent may run

Pass `actions=` to `Agent`. Any of these work:

- A dict of plain functions, as is: `{"notes.add": add_note}`. The first line of
  each docstring is the summary the agent sees; parameters come from the signature.
- `aiify.actions.from_functions(funcs, destructive=[...], mutating=[...])` to mark
  which functions change data and which destroy it.
- `aiify.actions.from_dispatch(dispatch, describe, root=...)` for an app that
  already has a JSON action runner (the agentify pattern): `dispatch(name, params)`
  returns `{"ok": ..., "result": ...}` and `describe()` lists the actions.
- `aiify.actions.from_registry(mapping)` for a `{name: spec}` registry whose specs
  carry `fn`, `summary`, `mutates`, `destructive`.
- `aiify.actions.combine(a, b, ...)` to offer several of these as one list, for
  example the app's registry plus a few lookups written for the assistant.

Names are free text; dotted names (`plot.bar`) read well and work with patterns.

## Approval

An action asks the person first when it is marked destructive, when the profile's
`confirm` patterns match it, or when the app itself answers `requires_confirmation`.
With the panel open, a card shows the action, its parameters and "Run it" / "Don't";
it waits 90 seconds, and no answer counts as no. Without an open panel the reply is
`requires_confirmation`, and the agent must ask in its own words before repeating
the command with `--confirm`, which the person then approves as a command.

## Choosing marks

- Read-only (the default): looks things up, changes nothing.
- `mutating`: changes data but is easy to undo or repeat (add, rename, select).
- `destructive`: deletes or overwrites (clear outputs, remove a recording). Mark
  these; the approval card is the only thing between the agent and the data.

Results must be JSON-friendly; ai-ify converts dates, paths, numpy values and
dataclasses, and turns NaN or infinity into null.

Related topics (read with context.read): profiles, agent-commands, troubleshooting
```

## Profiles, instructions and app state (`profiles`)

````markdown
ai-ify 0.2.0 — Profiles, instructions and app state

## Profiles: set-ups the person picks from

`profiles={"name": Profile(...)}` lists the choices in the panel's first picker
(hidden when there is only one). Switching profile starts a new chat.

```python
from aiify import Profile, When
Profile(
    provider="claude",            # or "codex"
    model=None, effort=None,      # starting values; None keeps the agent's own default
    mode=None,                    # the agent's permission mode
    allow=("*",),                 # glob patterns of actions it may run at all
    confirm=("*delete*",),        # patterns that always ask first
    deny=(),                      # patterns refused even when allowed
    instructions="...",           # text, or a function of the app state returning text
    rules=(),                     # When rules for this profile only
    label="Assistant",            # name shown in the picker
)
```

A look-only profile: `Profile(allow=["*.list", "*.summary"], label="Look only")`.
Actions it may not run are hidden from the agent's `action.list`.

The model, effort and mode pickers show what the running agent offers; the person
can change them at any time, and a change applies to the next message.

## What the agent is told

- `guide=` (text, a callable, or an object with `read()`): what the app is, sent
  with the first message of each chat.
- `instructions=` on the `Agent` (every profile) and on a `Profile`.
- `state=`: a function returning a small JSON-friendly dict of what the app holds
  now. It is sent with every message (cut at 6000 characters), merged with what
  the page reports through `window.aiify.setState`.
- `rules=[When(...)]`: extra instructions added only to messages they match, on
  the app state, what was typed, or the model and effort, e.g.
  `When(lambda s: s.get("view") == "plots", "Plots are on screen; prefer plot.* actions.")`.
- `launches=`: the app's own buttons that start the assistant, each with its own
  context.

Any of these texts can be a function, called for each message. The `context` topic
covers rules, launches and context functions.

Related topics (read with context.read): actions, page-control
````

## The app's own context, rules and launch buttons (`context`)

````markdown
ai-ify 0.2.0 — The app's own context, rules and launch buttons

## The app's own context

Everything the app tells the agent is text, or a function that returns text. A
function is called for each message with a `Turn`, so it can look at what is
happening right now:

| `Turn` field | What it holds |
|---|---|
| `text` | What the person typed |
| `state` | The app state sent with the message |
| `provider`, `model`, `effort`, `mode` | The agent's settings for this message |
| `profile` | The profile in use |
| `launch`, `data` | The launch (app button) that started this chat, and the data it passed |
| `first` | Whether this is the chat's first message |

A function that returns `None` or `""` adds nothing. One that raises is reported to
the agent as "the app's ... could not be built", and the message still goes.

## Rules: context added when something is true

`rules=[When(...)]` on the `Agent`, a `Profile` or a `Launch`. A rule adds its
`add_instructions` to a message when every condition it names holds:

```python
from aiify import When

rules=[
    # what the person typed: a word (matches words starting with it, any case),
    # a list of words, a compiled regex, or a function of the text
    When(prompt=["cost", "price"], add_instructions=lambda turn: price_note(turn.state)),
    # the agent's settings: a name or glob pattern, or a list of them
    When(model="opus*", effort=["high", "xhigh"], add_instructions="Check every number twice."),
    When(provider="codex", add_instructions="Use action.run, not shell commands, to change data."),
    # what the app shows (the first argument is a test of the state)
    When(lambda s: s.get("view") == "plots", "Plots are on screen; prefer plot.* actions."),
    # no condition: every message, built fresh each time
    When(add_instructions=lambda turn: f"Selected cells: {selection()}"),
]
```

`profile=` and `launch=` conditions work the same way. A rule's text is built only
when the rule matches, so `price_note` runs only for messages that mention a cost.
Give a rule a `name=` to make a failure report easier to trace.

## Launches: the app's buttons start the assistant

A launch is one way into the assistant, with its own context. Declare them on the
`Agent`:

```python
from aiify import Agent, Launch

agent = Agent("my-app", ...,
    launches={
        "explain-figure": Launch(
            label="Explain this figure",          # shown in the chat: "Started from: ..."
            profile="analyst",                    # switch profile (optional)
            model="opus", effort="high",          # settings for this chat (optional)
            instructions=lambda turn: figure_notes(turn.data["figure"]),
            rules=[When(prompt="error bar", add_instructions="Error bars are SEM.")],
            message=lambda turn: f"Explain figure {turn.data['figure']}.",
        ),
        "ask-about-samples": Launch(label="Ask about samples", new_chat=False,
                                    instructions="They are looking at the sample table."),
    })
```

Start one from the page, with any JSON data:

```html
<button data-aiify-launch="explain-figure" data-aiify-data='{"figure": "fig2"}'>Explain</button>
<script>aiify.launch("explain-figure", {figure: "fig2"})</script>
```

or from Python with `await agent.launch("explain-figure", {"figure": "fig2"})`.

What happens:

1. The panel opens. A new chat starts (switching to `profile` when given), unless
   `new_chat=False`, which keeps the current conversation.
2. `model`, `effort` and `mode` are applied. The person can still change them.
3. The launch's `instructions` and `data` go with the next message, once. Its
   `rules` apply to every message of this chat.
4. `message`, if set, is sent at once as if the person typed it. Leave it empty
   to let them type.

A new chat from the panel ends the launch.

## Which context goes where

| Context | When it is sent |
|---|---|
| `guide=`, `instructions=` (Agent, Profile), launch `instructions` | With the first message of a chat (a launch's: the message after it starts) |
| `state=` and the page's `setState` | Every message |
| Rules (Agent, Profile, Launch) | Every message they match |

Hooks before and after each message, suggested prompts, locked pickers and
attachments are in the `chat-options` topic.

Success check: send a message containing a rule's word to the scripted fake agent
with `echo` in it (see the `testing` topic); the reply quotes the rule's text.

Related topics (read with context.read): profiles, page-control
````

## What the agent finds by itself, and the app map (`discovery`)

````markdown
ai-ify 0.2.0 — What the agent finds by itself, and the app map

## What the agent finds by itself

With no extra code, the agent learns the app from:

| Source | What it gets |
|---|---|
| The app's web routes | Each JSON route becomes an action, `route.<function name>`, with its parameters and docstring |
| HTML pages | Listed by path and docstring, for `how` |
| The guide | Every topic, when the guide has `topics()` and `read(topic)` (the agentify layout) |
| The README | Next to the app's package, or up to two folders above it |
| The screen | Named page commands and labelled controls, while a page is open |
| App notes and the app map | When the app has them (below and the `chat-options` topic) |

Routes that only read (GET) run freely. Every other method asks the person first,
like a destructive action. Routes are called inside the app's process.

```python
Agent("my-app", routes=True)                   # the default: every JSON route
Agent("my-app", routes=["/api/samples*"])      # only these paths
Agent("my-app", routes=False)                  # none
```

A profile's `allow` and `deny` patterns apply to `route.*` names like any action.

## How the agent asks "how do I..."

The agent runs `aiify --app my-app how "export the summary as CSV"`. It gets the best
matches from everything above, each with how to use it: an action to run, a control
to click, or a section of the guide, README or app map. The search is local: no
tokens, no network, and no setup.

## The app map: built by the developer, once per release

A search finds the right pieces; it cannot explain a task that takes several
steps. The app map does that. It is a Markdown file of the app's screens, tasks
("How to ..." with numbered steps, by their on-screen labels) and terms. A hidden
conversation on the developer's own subscription reads the source and writes it:

```bash
python -m aiify.appmap build myapp.main:app          # or myapp.main:create_app, or the Agent
python -m aiify.appmap check myapp.main:app          # exit 1 when the source changed since
```

It writes `aiify_map.md` in the app's package folder. Ship that file with the
package, for example as package data. The running agent finds it there with no
setting (`Agent(app_map="path")` points elsewhere, `app_map=None` ignores it).
The map's overview goes with the first message of each chat, and each task
becomes a `how` result.

The map records a fingerprint of the source. `how` reports `"app_map": "out of
date"` once the source has changed, and `check` fails, which suits a release
check or CI. Building it reads the source only: every tool that would change
something is refused. `--provider codex`, `--model` and `--effort` choose the agent.
A small app takes under a minute; a large one, several.

Success check: `python -m aiify.appmap check myapp.main:app` prints "is current", and
`aiify --app my-app how "<a task from the map>"` lists that task first.

Related topics (read with context.read): context, agent-commands
````

## Hooks, suggestions, locked pickers, ask, attachments, notes, queue and schedule (`chat-options`)

````markdown
ai-ify 0.2.0 — Hooks, suggestions, locked pickers, ask, attachments, notes, queue and schedule

## What the app can switch on

Every option here is off until the app turns it on.

```python
from aiify import Agent, Answer, Profile

agent = Agent("my-app", ...,
    before_send=check,            # look at (or answer, or rewrite) each message first
    after_reply=log_reply,        # see each reply when it ends
    suggestions=["Which samples are excluded?", "Summarise this plate"],
    queue=True,                   # Tab queues a message while the agent answers
    schedule=True,                # "Later" sends a message at a set time
    attachments=True,             # the person can attach files (button, paste, drop)
    notes=True,                   # notes kept for this app across chats
    profiles={"main": Profile(lock=["model"], limit={"effort": ["low", "medium"]})},
)
```

## Hooks: before a message goes, after a reply ends

`before_send(turn)` gets the `Turn` (the `context` topic lists its fields) and returns:

| Return | What happens |
|---|---|
| `None` | The message goes as typed |
| text | That text goes instead; the chat still shows what was typed |
| `Answer("...")` | The app replies itself; the agent is not asked and nothing is charged |

If `before_send` raises, the message is held back and the panel shows "The app could
not check this message: ...".

`after_reply(turn, reply)` gets an `AgentReply`: `text`, `stop` (`end_turn`,
`cancelled`, `error: ...`), `tools` (tool calls made) and `total` (seconds). Use it to
log replies or update the app. Its errors are logged, never shown.

Both may be `async`. A plain function runs on the agent's event loop, so keep it quick.

```python
def check(turn):
    if "price" in turn.text.lower():
        return Answer(f"The plan costs {price()} a month.")
```

## Suggested prompts

`suggestions=` on the `Agent`, a `Profile` or a `Launch`: text, `{"label": ..., "text":
...}`, or a function of the `Turn` returning them. They show as buttons while the chat
is empty, and right after a launch. A launch's replace the profile's, which replace
the app's. Up to 8 are shown.

## Locked and limited pickers

On a `Profile` or a `Launch`:

- `lock=["model", "effort"]`: these pickers are hidden and the person cannot change
  them. Any of `profile`, `provider`, `model`, `effort`, `mode`.
- `limit={"effort": ["low", "medium"], "model": ["sonnet*"]}`: only matching values
  are offered (glob patterns). A setting outside the limit moves to the first allowed
  value when the chat starts.

The app's own `agent.configure(...)` calls are not limited.

## One-off questions from the app's code

```python
summary = await agent.ask("Describe this plate in one sentence.")
result = await agent.ask("Which wells look contaminated?", schema=Wells)  # pydantic model or JSON Schema dict
```

`ask` runs a separate, hidden conversation on the person's subscription. The chat is
not touched. With `schema`, the reply is read as JSON and checked; if that fails, the
agent is asked once more. `context=False` leaves out the app guide and state.
`provider`, `model` and `effort` choose the agent. Tools that need approval are
refused. It raises `AiifyError` with code `signed_out` when there is no subscription
sign-in.

From a thread (Qt apps using `start_background`):
`asyncio.run_coroutine_threadsafe(agent.ask("..."), agent.loop).result()`.

## Attachments

The app can attach files or text to the next message at any time:

```python
agent.attach("plate.csv", path="results/plate.csv")     # or text=..., data=b"...", data_url=...
await agent.launch("explain-figure", {"figure": "fig2"}, attach=[{"name": "fig2.png", "data": png}])
```

```js
aiify.attach({name: "selection.txt", text: selectedText});
aiify.attach({name: "plot.png", dataUrl: canvas.toDataURL()});
aiify.launch("explain-figure", {figure: "fig2"}, [{name: "fig2.png", dataUrl: url}]);
```

Each is saved in the agent's work folder, under `attachments/`, and the agent is told
the path, so Claude and Codex read it, images included. Short text also goes in the
message. The limit is 10 MB each. With `attachments=True` the person can attach files
too, by the Attach button, by pasting or by dropping them on the panel. A page can
never attach a file from the computer by its path; only Python code can.

## App notes

`notes=True` keeps a Markdown file of notes for the app (`app-notes.md` in its work
folder, or the path given). The agent reads it at the start of each chat. It adds a
line when the person asks it to remember something, with the app's own command
(`notes.add text="..."`), so no approval is needed. Use `agent.notes.read()`,
`.add(text)` and `.clear()` from code.

## Queued and scheduled messages

With `queue=True`, while the agent answers, Tab (or Enter) adds the typed message to
a queue shown above the text box. Each goes when the reply before it ends. ✕
removes one. Stop also hands the queue back to the text box, so nothing is sent
behind the person's back.

With `schedule=True`, "Later" opens a time picker: the message goes at that time,
or straight after the reply running then. Scheduled messages are kept only while
the app runs.

From code: `agent.queue_message(text)`, `agent.schedule_message(text, at)` (`at`: a
datetime, a timedelta from now, or an ISO time) and `agent.remove_pending(id)`.

Success check: with the demo (`python examples/demo_app.py --fake`), send "slow",
press Tab on a second message, and see it go when the first ends.

Related topics (read with context.read): context, profiles
````

## Let the agent use the page (`page-control`)

````markdown
ai-ify 0.2.0 — Let the agent use the page

## The panel

Add one tag to the page after `agent.mount(app)`:

```html
<script src="/aiify/panel.js" defer></script>
```

Optional attributes: `data-open="true"` (start open), `data-theme="dark|light"`,
`data-title="..."`, `data-bridge="false"` (chat only; the agent cannot act on the page).
The panel lives in a shadow root, so the page's styles and the panel's do not mix.
A page with a Content Security Policy needs `connect-src 'self'` (which covers the
websocket on the same host) and must allow the script from its own origin.

## Named UI commands

Register page functions the agent can call by name (`aiify ui do NAME key=value`):

```html
<script>
document.addEventListener('DOMContentLoaded', () => {
  window.aiify.registerTool({
    name: 'show_view',
    description: 'Switch between the table and the summary',
    inputSchema: {type: 'object', properties: {view: {enum: ['table', 'summary']}}, required: ['view']},
    execute: async ({view}) => { showView(view); return {view}; },
  });
  window.aiify.setState(() => ({view: currentView, selected: selectedId}));
});
</script>
```

Run this after `panel.js` (it is deferred, so wait for `DOMContentLoaded` or place
the code in a later deferred file). `setState` reports what is on screen; it is
merged into the state sent with each message and returned by `aiify state`.

## The control tree

`aiify ui tree` lists visible controls with refs. Make important ones stable:

```html
<button data-agent="export-bundle">Export</button>   <!-- ref "export-bundle" never changes -->
<div data-agent="off">...</div>                       <!-- hidden from the agent entirely -->
```

Numbered refs (`e12`) go stale after the page changes; the reply then says
`stale_ref` and the agent lists the tree again. Prefer, in order: a backend action,
a named UI command, a named control, then a numbered one.

Related topics (read with context.read): agent-commands, troubleshooting
````

## How the panel looks and where it sits (`panel-look`)

````markdown
ai-ify 0.2.0 — How the panel looks and where it sits

## Adding the panel to the page

Either let ai-ify add it to every HTML page the app serves:

```python
agent.mount(app, inject=True)                          # every page
agent.mount(app, inject=lambda path: path == "/")      # only the pages you choose
```

or put the tag in the page yourself, before `</body>`:

```html
<script src="/aiify/panel.js" defer></script>
```

`aiify.web.panel_tag(**options)` returns that tag with options filled in, for apps
that build their pages in Python. `inject` skips pages that already load
`panel.js`, non-HTML responses, compressed responses and FastAPI's `/docs`.

## Where it sits

| Layout | What the person sees |
|---|---|
| `overlay` (default) | A round button bottom-right; the panel slides over the right edge of the app |
| `dock` | The app's page shrinks to make room, so nothing is covered |
| `float` | A separate window over the app: drag it by its title bar, resize it from its bottom-right corner |
| `inline` | The panel fills an element of the app's choosing (a tab, a side column), always open |

The person can switch between overlay, dock and float with the "view" picker in the
panel, and set "opacity": lower values thin the panel's background (never its text)
so the app shows through while both are in view. Both choices, and the window's
place and size, are remembered in that browser.

## Options

Set them as `panel={...}` with `inject=True`, as `panel_tag(...)` arguments, or as
`data-` attributes on the script tag:

| Option | Values | Effect |
|---|---|---|
| `layout` | `overlay`, `dock`, `float`, `inline` | Where the panel starts (the person's own choice wins once made) |
| `target` | a CSS selector, e.g. `#ai` | The element an `inline` panel fills |
| `opacity` | `30` to `100` | How solid the background starts |
| `launcher` | `none` | No round button; the app opens the panel itself |
| `accent` | a CSS colour | Buttons, links and bars in the app's colour |
| `font` | `system`, or a CSS font list | The panel uses the page's font unless told otherwise |
| `theme` | `light`, `dark` | Force a theme (default follows the system) |
| `title` | text | Panel title (default "Assistant · app name") |
| `open` | `true` | Start open |

```python
agent.mount(app, inject=True, panel={"layout": "float", "opacity": 85, "accent": "#2b6cb0"})
```

With `launcher: none`, open the panel from the app's own button:

```html
<button onclick="aiify.open()">Assistant</button>
```

`aiify.open()`, `aiify.close()`, `aiify.toggle()`, `aiify.setLayout("dock")` and
`aiify.setOpacity(70)` work from any script on the page.

Success check: open the page; the panel appears as chosen, and after picking
another view and reloading, the panel comes back the same way.

Related topics (read with context.read): page-control, quickstart
````

## The aiify command and its replies (`agent-commands`)

````markdown
ai-ify 0.2.0 — The aiify command and its replies

## The aiify command

Any agent or script on the same computer can drive a running app:

```
aiify apps                                    # running apps with ai-ify
aiify --app NAME describe                     # what the app offers
aiify --app NAME state                        # what it shows now
aiify --app NAME action.list [match=plot.*]
aiify --app NAME action.describe NAME
aiify --app NAME action.run NAME key=value ... [--confirm]
aiify --app NAME ui tree [match=export]
aiify --app NAME ui click REF | ui fill REF VALUE | ui select REF VALUE | ui read REF
aiify --app NAME ui do NAME key=value ...
aiify --app NAME wait [timeout=5]             # until the page changes
```

`python -m aiify` is the same command. Without `--app`, the only running app is
used. Values are read as JSON when they parse (`n=3`, `ids=[1,2]`), else as text.
The reply is printed as JSON with `"ok"`; the exit status is 0 when ok.

The embedded agent is told these commands itself, and its own plain `aiify`
commands for this app run without asking the person each time. Commands joined
with `;` or `&&` are fine; pipes, redirects, other programs, `--confirm` and
`raw` requests are shown to the person to approve.

## Error codes

| code | meaning |
|---|---|
| `denied` | the profile forbids it, or the person said no |
| `requires_confirmation` | needs the person's approval; ask, then repeat with `--confirm` |
| `unknown_action` | no such action; run `action.list` |
| `no_ui` | no page is open, so `ui.*` cannot run |
| `stale_ref` | the page changed; run `ui tree` again |
| `invalid` | malformed request or parameters |
| `timeout` | the app or page did not answer in time |
| `failed` | the action raised an error; the message says what |

Related topics (read with context.read): actions, page-control, troubleshooting
````

## Console, usage limits and Codex accounts (`console-and-limits`)

```markdown
ai-ify 0.2.0 — Console, usage limits and Codex accounts

## Console

"Console" in the panel opens the same conversation in a terminal (`claude --resume`
or `codex resume`), for long work or for the vendor's own commands. It uses the CLI
on the PATH when installed, otherwise the copy the adapter brings (through `npx`). The next
message typed in the panel picks up what was said there. The button is greyed out
until the agent has started (its status line reads "ready").

## Subscription limits

Bars under the pickers show how full each limit of the agent in use is (5-hour,
weekly, and weekly per model where the subscription has one), with reset times.
A bar turns amber at `limit_warning` (default 0.9, i.e. 90%):
`Agent(..., limit_warning=0.8)`.

- Claude readings come from the agent's own reports and from Claude Code's local
  `/usage` command, run in a separate short session after a message at most every
  10 minutes. It uses no tokens. Change the interval with
  `Agent(..., limit_check_every=1800)`, or turn it off with `None`.
- Codex readings come from Codex's own session logs (`$CODEX_HOME/sessions`).

The bars appear after the first message; until then there is no reading.

## Several Codex accounts

When `codex-profiles` is installed and more than one account is saved, the panel
shows an account picker while Codex is the agent. A switch requested during a
reply happens when that reply ends; the next message restarts Codex signed in as
the chosen account and continues the same conversation. Only the active account
is ever asked for its usage. Pass `codex_accounts=None` to hide the picker.

Related topics (read with context.read): setup, troubleshooting
```

## Apps without a web page, and optional embedding (`other-apps`)

````markdown
ai-ify 0.2.0 — Apps without a web page, and optional embedding

## Apps without FastAPI

`agent.mount(app)` needs a FastAPI (or Starlette-compatible) app; it ties the
agent to the app's start and stop. Other apps can still offer backend actions to
outside agents through the control port:

```python
agent = Agent(app="myqtapp", actions=registry)
agent.start_background()        # the control port on its own thread
...
agent.stop_background()         # when the app quits
```

`aiify --app myqtapp action.list` then works from any terminal or agent session.
There is no in-app chat panel for non-web apps yet.

## Turning the assistant on and off

Keep ai-ify optional in an app that is published for others: import it only when
a setting or environment variable asks for it, and catch `ImportError`. For
example Circadian Workbench mounts it only when `CIRCADIAN_WORKBENCH_AI=1` and
the `ai` extra is installed, and its frozen Windows build excludes `aiify` and `acp`.

## Agent start-up

The agent process starts when a panel connects (so the pickers fill and the first
reply is quicker), or at app start with `Agent(..., prewarm=True)`. It runs in
the app's work folder and is stopped, with any child processes, when the app stops.

Related topics (read with context.read): actions, agent-commands
````

## Test an app that embeds ai-ify (`testing`)

````markdown
ai-ify 0.2.0 — Test an app that embeds ai-ify

## Testing an app that embeds ai-ify

Tests should never start Claude or Codex. ai-ify ships a scripted stand-in agent:

- `AIIFY_ENGINE_COMMAND='["python", "-m", "aiify.testing.fake_agent"]'` (a JSON list)
  replaces the adapter command for every agent in the process and its children.
  Alternatively pass `engine_argv={"claude": [...], "codex": [...]}` to `Agent`.
- `FAKE_ACP_STORE=<file>` is where the fake keeps its sessions (use a temp folder).
- `AIIFY_HOME=<temp folder>` keeps the app registry and work folders out of the
  real per-user folder.

The fake agent's replies depend on the message: "echo ..." returns the whole
message it received (useful to check instructions and state reached it),
"permission" asks one permission, "slow" streams until cancelled, "history" says
how many messages the session has had, "/usage" returns a limits report; anything
else answers "hello from fake".

To check the control levels in a browser test, start the app server with these
variables, open the page, then drive it with the `aiify` command:

```python
from aiify.cli import main
import io, json
out = io.StringIO()
code = main(["--app", "notes", "ui.do", "show_view", "view=summary"], out=out)
reply = json.loads(out.getvalue())
```

An action that needs approval shows its card in the page as `#aiify-root .perm`
(inside the panel's shadow root); clicking its "Don't" button makes the command
return `denied`.

Related topics (read with context.read): quickstart, agent-commands
````

## Recognise a problem and check recovery (`troubleshooting`)

```markdown
ai-ify 0.2.0 — Recognise a problem and check recovery

## The panel says "disconnected - retrying..."

The page cannot open the websocket at `/aiify/ws`. If the server log shows
"No supported WebSocket library detected", install one: `pip install "ai-ify[web]"`
(it brings `websockets`). If the browser console shows a Content Security Policy
error, add `connect-src 'self'`. Recovery: the status line changes to "ready".

## The status stays at "starting the assistant..." or shows an error

The agent adapter did not start. Check that `npx --version` works in the same
environment the app runs in; without Node.js the panel says so and links to
nodejs.org. The first start downloads the adapter and can take a minute.
Recovery: the model and effort pickers fill in.

## The panel shows "Sign in to Claude" (or ChatGPT)

The agent found no subscription login on this computer. "Sign in" runs the
vendor's own sign-in, which opens a sign-in page in the browser. If that page opened
behind other windows, the card links to it. If the page shows a code, paste it into
the card. Then the chat carries on and the message that was waiting is sent.
Recovery: the card disappears and the status line reads "ready".

## The agent asks the person to approve every command

Its commands are not plain `aiify` commands for this app: they were wrapped in
other shell code (`if`, pipes, loops), used another app name, or carried
`--confirm`. Plain commands, alone or joined with `;`, run without asking.

## `requires_confirmation` from the command line

The action needs approval and no panel is open to show a card. Ask the person,
then repeat with `--confirm`.

## `no_ui`

No page with the panel is open, so on-screen commands cannot run. Backend actions
still work. Open the app's page (the panel can stay closed).

## `stale_ref`

The page changed after the tree was listed. Run `aiify ui tree` again, or give the
control a `data-agent` name so its ref never changes.

## No limit bars

There is no reading until the first message ends. Claude's full reading comes from
a separate `/usage` check, which needs the adapter to start a second time; it is
skipped when `limit_check_every=None`.

## The account picker is missing

It appears only while Codex is the agent, `codex-profiles` is on the PATH, and
more than one Codex account is saved (`codex-profiles list`).

Related topics (read with context.read): setup, page-control, agent-commands
```
