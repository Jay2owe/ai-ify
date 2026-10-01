# aiify agent guide

Package version: `0.1.0`

Read-only usage guide generated from the package's public context module.

Structured companion: `aiify_context.json`.

## Reader

```python
from aiify import context; context.read(format='json')
```

## What ai-ify does (`overview`)

````markdown
ai-ify 0.1.0 — What ai-ify does

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
- `page-control` — Let the agent use the page: The panel tag, named UI commands, page state and the control tree.
- `agent-commands` — The aiify command and its replies: Commands agents use to drive a running app, and error codes.
- `console-and-limits` — Console, usage limits and Codex accounts: Open the chat in a terminal; limit bars; account switching.
- `other-apps` — Apps without a web page, and optional embedding: Control port only, background start, keeping ai-ify optional.
- `testing` — Test an app that embeds ai-ify: The scripted fake agent and isolated folders.
- `troubleshooting` — Recognise a problem and check recovery: Panel, start-up, approvals, error codes, limits.
````

## Install and sign in (`setup`)

```markdown
ai-ify 0.1.0 — Install and sign in

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
ai-ify 0.1.0 — Add an assistant to a small app

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
ai-ify 0.1.0 — Offer backend actions

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
ai-ify 0.1.0 — Profiles, instructions and app state

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
- `rules=[When(predicate, text)]`: extra instructions added only while
  `predicate(state)` is true, e.g.
  `When(lambda s: s.get("view") == "plots", "Plots are on screen; prefer plot.* actions.")`.
  A predicate that raises counts as false.

Related topics (read with context.read): actions, page-control
````

## Let the agent use the page (`page-control`)

````markdown
ai-ify 0.1.0 — Let the agent use the page

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

## The aiify command and its replies (`agent-commands`)

````markdown
ai-ify 0.1.0 — The aiify command and its replies

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
ai-ify 0.1.0 — Console, usage limits and Codex accounts

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
ai-ify 0.1.0 — Apps without a web page, and optional embedding

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
ai-ify 0.1.0 — Test an app that embeds ai-ify

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
ai-ify 0.1.0 — Recognise a problem and check recovery

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

The agent found no subscription login on this computer. "Sign in" opens the
vendor's own sign-in: for Claude a small terminal window that opens the browser,
for Codex the browser directly. The card waits, then the chat carries on and the
message that was waiting is sent. If the card keeps waiting after the browser says
you are signed in, press "I've signed in". Recovery: the card disappears and the
status line reads "ready".

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
