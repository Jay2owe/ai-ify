## What the agent finds by itself

The default uses local guidance search and an app map when one is shipped. A
verified bundle supplied by the host app starts enabled. Extra web-route actions
are opt-in. This matches the lowest-token configuration in the Circadian
Workbench evaluation; token use in other apps can differ.

For a host with a verified bundle:

```python
Agent("my-app", prepared="aiify_prepared")
```

| Setting | Default | What the agent gets |
|---|---|---|
| `routes=True`, or a list of path patterns | Off | Each JSON route as an action, `route.<function name>`; the app's pages for `how` |
| `how=True` | On | The `how` search over the guide, README, actions, screen and app map |
| `app_map="auto"`, or a path | Auto-discover a shipped map | The map's overview with each chat's first message; its tasks in `how` |
| `prepared=` a bundle folder | Enabled when supplied | The bundle's actions, and its guide as one more topic |

Enable extra route actions with `Agent("my-app", routes=True)` or a path list.
Use `how=False` and `app_map=None` to disable guidance search and map discovery.
No map or prepared bundle is generated while the app runs.

Routes that only read (GET) run freely. Every other method asks the person first,
like a destructive action. Routes are called inside the app's process.
`routes=["/api/samples*"]` offers only those paths.

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
package, for example as package data. `Agent(app_map="auto")` finds it there
(`app_map="path"` points elsewhere).
The map's overview goes with the first message of each chat, and each task
becomes a `how` result.

The map records a fingerprint of the source. `how` reports `"app_map": "out of
date"` once the source has changed, and `check` fails, which suits a release
check or CI. Building it reads the source only: every tool that would change
something is refused. `--provider codex`, `--model` and `--effort` choose the agent.
A small app takes under a minute; a large one, several.

Success check: `python -m aiify.appmap check myapp.main:app` prints "is current", and
`aiify --app my-app how "<a task from the map>"` lists that task first.
