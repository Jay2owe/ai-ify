# Embedding ai-ify in an app

This is the human walk-through. The same facts, split into topics an agent can
read, ship with the package: `python -m aiify.context [topic]` or
[README_AI.md](../README_AI.md). Circadian Workbench is the worked example
throughout ([integration record](integrations/circadian-workbench.md)).

## The idea in one picture

```
 person ──chat──> panel.js ──websocket──> Agent (in the app's process)
                                            │  starts Claude/Codex via ACP (npx adapter)
                                            ▼
 Claude/Codex ──runs──> aiify --app X ... ──TCP, 127.0.0.1──> control port
                                            │
             ┌──────────────────────────────┼──────────────────────────────┐
             ▼                              ▼                              ▼
     backend actions                 named UI commands                control tree
   (Python functions)          (registerTool in the page)    (every visible control)
```

The agent never gets a special API into the app. It runs `aiify` commands like
any other agent would, and the app's profile decides which of them are allowed
and which ask the person first.

## Step 1: decide what the agent may do

For an app with missing actions, `python -m aiify.prepare build ./myapp` can
generate wrappers over its existing backend, usage guidance and real-backend
tests. Review them and run `python -m aiify.prepare verify ./myapp/aiify_prepared`;
then `load_prepared` supplies an action source and guide for the steps below.
See [developer preparation](developer-preparation.md) or
`python -m aiify.context preparation`.

List the operations worth offering and mark each: read-only, mutating, or
destructive. If the app was already made agent-controllable with /agentify, its
action registry is the list: wrap it with `from_dispatch(dispatch, describe)`.
Add a few lookups written just for the assistant with `from_functions`, and
join them with `combine`.

Circadian Workbench offers its 84 analysis actions plus one new lookup:

```python
source = combine(
    from_dispatch(actions.dispatch, actions.describe, root=str(work / "outputs")),
    from_functions({"workbench.recordings": saved_recordings}),
)
```

`root` is where analysis outputs go: the assistant's own work folder, never the
person's data folder.

## Step 2: profiles and instructions

Give the person a sensible default and, if useful, a safer one:

```python
careful = ["clear_*", "*remove*", "*delete*"]
profiles = {
    "assistant": Profile(provider="claude", label="Assistant", confirm=careful),
    "look-only": Profile(provider="claude", label="Look only", allow=read_only_names,
                         instructions="Only look and explain: change nothing on disk."),
}
```

Write `instructions` the way you would brief a new colleague: what the app is,
where data comes from, which commands to prefer, what never to do. Add `When`
rules for states that change the advice ("the group overlay is on screen: results
there pool several recordings"). Pass the app's own usage guide as `guide=`
(Circadian Workbench passes its `context` module).

## Step 3: mount and add the page scripts

```python
agent = Agent(app="circadian", actions=source, guide=context, instructions=INSTRUCTIONS,
              profiles=profiles, state=lambda: {"version": __version__}, rules=[...])
agent.mount(fastapi_app)
```

and in the page, before `</body>`:

```html
<script src="/aiify/panel.js" defer></script>
<script src="assets/ai_commands.js" defer></script>
```

An app without named UI commands can skip the page edit: `agent.mount(fastapi_app,
inject=True)` adds the panel tag to every HTML page. The panel's layout (side,
docked, a draggable window, or inline in the app's own element), opacity, colour
and launch button are options: `python -m aiify.context panel-look`.

## Step 4: name what matters on the page

In `ai_commands.js`, register the handful of on-screen changes people actually ask
for, and report what is showing:

```js
ai.registerTool({
  name: 'show_view',
  description: 'Switch the main results view (the tabs above the results)',
  inputSchema: { type: 'object', properties: { view: { enum: views } }, required: ['view'] },
  execute: async ({ view }) => { selectView(view); return { view: activeView() }; },
});
ai.setState(() => ({ view: activeView(), open_recordings: [...] }));
```

Give the key buttons stable names (`data-agent="export-bundle"`) and hide anything
the agent must never touch with `data-agent="off"`. Everything else is still
reachable through the control tree.

## Step 5: keep it optional

A published app should not force the dependency on everyone. Circadian Workbench:

- declares an extra: `ai = ["ai-ify[web]>=0.1"]`
- mounts only when `CIRCADIAN_WORKBENCH_AI=1`, importing ai-ify through
  `importlib` so PyInstaller does not follow it
- excludes `aiify` and `acp` from its frozen build
- adds the page scripts only when the assistant is mounted

## Step 6: test it without a subscription

Start the app with `AIIFY_ENGINE_COMMAND='["python", "-m", "aiify.testing.fake_agent"]'`,
`FAKE_ACP_STORE` and `AIIFY_HOME` pointing at a temp folder, open the page in a test
browser, and drive it with `aiify.cli.main`. Circadian Workbench's
`tests/e2e/test_ai_assistant.py` checks that the panel loads, a backend action
lists the demo recording, `show_view` switches the view, the control tree leads
with a named button, and `clear_output` shows an approval card that "Don't" refuses.

## What the person sees

To connect multiple assistants, create one `aiify.MessageHub(local_database_path)`
and pass `messaging=hub.mailbox(stable_conversation_id, label=role_name)` to each
Agent. The package owns persistence, routing, commands and the shared Messages
control; the host supplies identities and optional small context metadata.
Use separate hubs for separate workspaces. No extra web server is required.
The shipped `messaging` guide covers replies, audit events and next-turn delivery.

One process can serve independent assistants on separate prefixes:

```python
from fastapi import FastAPI
from aiify import Agent, MessageHub

app = FastAPI()
hub = MessageHub("assistant-messages.sqlite3")
analysis = Agent("analysis", messaging=hub.mailbox("analysis"))
writing = Agent("writing", messaging=hub.mailbox("writing"))
analysis.mount(app, prefix="/analysis/aiify")
writing.mount(app, prefix="/writing/aiify")
# Each page embeds panel_tag() with its corresponding prefix.
# Start this one app once; mounting agents does not start additional web servers.
```

Each agent still owns its conversation, provider session and control port. Hosts
that add conversations dynamically manage their child app lifespans and URLs;
the same MessageHub and shared panel work with either hosting arrangement.

- An "AI" button bottom right; the panel opens beside the app and can be resized.
- Pickers for profile, agent (Claude or Codex), model, effort and mode.
- Limit bars for the subscription in use, amber when nearly full.
- Tool steps folded under the reply, and "Run X?" cards before risky actions.
- "Console" to continue the same conversation in a terminal.
