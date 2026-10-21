## The app's own context

Context callbacks have different inputs. Use the correct signature:

| Setting | Callback argument | When its text reaches the agent |
|---|---|---|
| `guide` | No arguments | First message of each chat |
| Agent/Profile `instructions` | State dictionary | First message of each chat |
| `state` | No arguments; returns a dictionary | Every message |
| `When.add_instructions` | `Turn` | Every matching message |
| Launch `instructions`, `message` | `Turn` | When the launch begins |
| `suggestions` | `Turn` | When building the prompt choices |

`Turn` describes the message and app state:

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
            effort="high",                        # use an effort offered by your adapter
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

## Recommended use

Keep stable guidance short and use state/actions for live facts. Instruction
callbacks may be evaluated again even when orientation is not resent; they should
read facts rather than change data. Use named rules for per-turn context. Rules
add together; they do not choose a single winner. A predicate exception prevents
that rule from matching. Instruction-building exceptions are reported as text.

For an explicit change of role, use a new chat. Launch `profile` must be a key
in `profiles`; an unknown key fails at construction. Launch data should contain
stable IDs and the meaning of a selection, rather than entire datasets. Plain
word conditions match word prefixes: `prompt="cost"` matches `costs`, not
`accost`. Use a compiled regex when exact word matching matters.
