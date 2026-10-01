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