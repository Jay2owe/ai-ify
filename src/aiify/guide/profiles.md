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