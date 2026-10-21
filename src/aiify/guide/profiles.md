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

Callback inputs differ: guide takes no arguments, instructions take state, and
rules take a `Turn`. Orientation is sent only at the first message; use rules
for instructions that must reach every turn. The `context` topic covers these
signatures and launch behavior.

## Changing settings and checking permission boundaries

From a started agent, `await agent.configure(profile="viewer")` selects an
existing profile and begins a new chat; changing provider does the same.
`await agent.configure(model=choice, effort=effort_choice)` changes adapter
settings. Obtain both values from the running adapter, not a guessed model ID.
Host code can override picker locks; use `by_person=True` when a custom settings
UI must enforce the configured lock/limit rules.

`deny` takes priority over `allow`; destructive actions ask even when allowed.
Unflagged mutating actions run without a card unless a `confirm` pattern matches.
Verify `action.list` under each profile, then check a denied call and a declined
write against actual app state. Action patterns restrict backend actions; page
commands and vendor-agent tools need their own host/provider controls. A viewing
profile does not restrict filesystem access by itself.
