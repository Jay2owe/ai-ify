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
