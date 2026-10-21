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

Start with `context.read("features")` for all features, configuration options
and links to detailed usage. Read `integration` to choose how to embed ai-ify,
`best-practices` for a complete implementation recipe and recommended patterns,
or `programmatic` to call it from application code. Read `quickstart` for the
smallest runnable example, or `agent-commands` to use an existing integration.

Minimal use in a FastAPI app:

```python
from aiify import Agent, Profile
agent = Agent(app="myapp", actions={"notes.add": add_note},
              profiles={"default": Profile(provider="claude")})
agent.mount(fastapi_app)      # then add <script src="/aiify/panel.js" defer></script> to the page
```

Read a topic with `context.read("<topic>")`; search with `context.search("<words>")`.

## Read the guide without starting an assistant

```python
from aiify import context

print(context.read("features"))
result = context.search("scheduled messages", limit=3)
assert result["ok"]
for match in result["results"]:
    print(match["topic"], match["description"])
structured = context.read("best-practices", format="json")
assert structured["ok"]
```

Reads and searches are offline and read-only. They do not start an app, import
its assistant backend or contact a provider. Structured reads include version,
topic, title, content, prerequisites and related topics. Required prerequisites
are included in the content; follow optional related topics when needed.
Unknown topics return helpful errors and available names (`ok: false` in JSON).
Search results have stable topic names and relevance descriptions; no match is
an empty list. `truncated: true` means more results exist; increase `limit` or
use a more specific query. Terminal reads/searches print JSON:
`python -m aiify.context features` or `python -m aiify.context --search "queue"`.
Agents without Python can read the generated portable Markdown or JSON guide.

Topics:
