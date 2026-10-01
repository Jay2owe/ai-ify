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
