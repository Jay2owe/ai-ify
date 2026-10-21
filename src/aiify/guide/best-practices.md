# Build a reliable assistant integration

Treat the assistant like a new colleague: give it a short handbook, current
facts and clearly named tools, then check the work it performs.

## A complete recipe: explain and edit session notes

This recipe demonstrates separate viewing/editing roles, approvals, app state,
conditional instructions, a launch button, a local answer and reply logging.
It uses in-memory text notes and the fake agent. Install `ai-ify[web]`, save as
`guided_notes.py`, and run `python guided_notes.py`. The fake spends no model
usage; remove `engine_argv` after following `setup` for real subscription use.

```python
import sys
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from aiify import Agent, Answer, Launch, Profile, When
from aiify.actions import from_functions

notes = []
reply_log = []

def list_notes():
    """Read all session notes."""
    return {"notes": list(notes)}

def add_note(text: str):
    """Add one non-empty text note."""
    if not isinstance(text, str) or not text.strip():
        raise ValueError("text must be non-empty")
    notes.append(text.strip())
    return {"count": len(notes)}

def clear_notes():
    """Delete every session note."""
    count = len(notes)
    notes.clear()
    return {"removed": count}

def before_send(turn):
    if turn.text.strip().lower() == "how many notes?":
        return Answer(f"There are {len(notes)} notes.")
    return None

def after_reply(turn, reply):
    # Store status/counts rather than copying confidential text into a log.
    reply_log.append({"stop": reply.stop, "tools": reply.tools})

app = FastAPI()

@app.get("/", response_class=HTMLResponse)
def page():
    return '''<h1>Session notes</h1>
    <button data-aiify-launch="summarise">Summarise notes</button>
    <script src="/aiify/panel.js" defer></script>'''

agent = Agent(
    "guided-notes",
    actions=from_functions(
        {"notes.list": list_notes, "notes.add": add_note, "notes.clear": clear_notes},
        mutating=["notes.add"], destructive=["notes.clear"],
    ),
    guide="Session notes are plain text. They are lost when this example stops.",
    state=lambda: {"note_count": len(notes)},
    profiles={
        "viewer": Profile(label="View notes", allow=["notes.list"]),
        "editor": Profile(label="Edit notes", allow=["notes.*"]),
    },
    profile="viewer",
    rules=[When(prompt="summary", name="summary-length",
                add_instructions="Use at most three bullet points.")],
    launches={"summarise": Launch(
        label="Summarise notes", profile="viewer",
        instructions="Read notes.list before summarising. Do not invent entries.",
        message="Summarise the session notes.",
    )},
    before_send=before_send, after_reply=after_reply,
    suggestions=["How many notes?", "Summarise the session notes"],
    engine_argv={"claude": [sys.executable, "-m", "aiify.testing.fake_agent"]},
)
agent.mount(app)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8771)
```

Success checks:

1. Open `http://127.0.0.1:8771/` and ask `How many notes?`. The app answers
   `There are 0 notes.` without a model turn.
2. In View notes, `aiify --app guided-notes action.list` lists only `notes.list`;
   `action.run notes.add text=hello` is denied.
3. Select Edit notes in the panel. Adding a note returns `count: 1`; clearing
   shows an approval card. Decline it and list notes to confirm nothing changed.
4. Send `echo summary`. The fake echoes the three-bullet rule, proving it arrived.
   The fake does not choose actions or write a real summary.
5. The Summarise notes button switches to View notes and begins that task's chat.
   Use a real agent only after the wiring and permissions checks pass.

## Expose useful tools with clear ownership

- Wrap existing backend functions. Return counts, IDs, output paths and relevant
  status so an agent can verify a result. Validate units, IDs and required state
  in the backend; model instructions are not input validation.
- Mark writes explicitly and mark deletion/overwrite destructive. Add profile
  confirmation patterns for other changes your app considers significant.
- Use allow patterns for deliberate action sets, and deny patterns for explicit
  exceptions. Deny wins; a destructive flag still requires approval.
- Keep operations on the app's real state. For registry callables taking `ctx`
  or `context`, provide `context_factory`; for a dispatcher, provide its root.
- Prefer backend actions for calculations and exports, named page commands for
  navigation, then stable `data-agent` controls, then temporary tree refs.

The action policy checks backend tools. Page tools and vendor-agent filesystem
or shell capabilities have separate boundaries. A viewing profile is not a
filesystem sandbox. Limit the vendor adapter's permissions through its supported
setup, and verify the actual tools used when measuring an agent's behavior.
`data-agent="off"` hides a page region from the control tree; it does not secure
its underlying API or files. Enforce access in the host as well.

## Give concise, timely context

- Put stable task instructions in `guide`; use `instructions` for the role's
  orientation. Both arrive with the first message. After changing them, start
  a new chat; use `When` rules for advice that must be refreshed each turn.
- `guide` callbacks take no arguments. Agent/Profile instruction callbacks take
  state. Rule, launch and suggestion callbacks take `Turn`, which includes text,
  settings, app state and launch data. Do not interchange those signatures.
- Keep state small: current selection, counts, units and output identifiers.
  The prompt cuts serialized state after 6000 characters. Use read actions or
  attachments for complete tables rather than assuming truncated text is intact.
- Python state overrides duplicate keys reported by the page. Give different
  concepts different keys and check `agent.current_state()` when wiring them.
- Use launch data for the selected item and `new_chat=True` for independent
  tasks. Use `new_chat=False` only when the previous conversation is relevant.
- Notes persist; queues and schedules do not. Use notes for user-requested
  preferences, not full data dumps or a substitute for the host's project records.

## Enable helpers deliberately

Start with local guidance search, which requires no generation. Ship an app map
when tasks span multiple screens; generate and check it before a release. Supply
prepared shortcuts only after reviewing their code/flags and passing real-backend
verification. Neither asset is created by normal chat.

Offer selected web-route paths when they are useful. Non-GET route approval
does not replace server authorization or backend validation. Do not use a GET
route for a write: ai-ify classifies GET as read-only.

Use `route_options` and panel Controls if people may enable host-approved routes.
After `agent.set_helpers(...)`, start `await agent.new_chat()` so the next chat
has consistent orientation. Compare helpers using task evaluations for your app;
results from another app do not establish your best configuration.

## Keep the interface responsive

Plain hooks and context callbacks run in the assistant's event loop; keep them
short. Use asynchronous hooks for waiting on I/O. Backend action execution uses
worker threads, so access GUI widgets through the GUI's own thread mechanism and
protect shared data as your host requires. `start_background()` does not solve
thread ownership.

`await agent.send` waits for the reply and returns its completion summary.
Observe events for the final text
for a visible conversation, or use `await agent.ask(...)` for a returned answer.
Avoid launching a separate `ask` for every keystroke: each is a new conversation
on the subscription. Use `before_send` and `Answer` for deterministic lookups.

Retain adapter defaults unless a task requires a change. Choose models from the
running adapter's choices; defaults are not a promise of lowest cost. A usage
warning is display feedback, not a hard stop. `prewarm=True` exchanges earlier
startup work for quicker readiness; it is unnecessary for guide reads or assets.

## Keep the assistant local and optional

The complete recipes bind the server to `127.0.0.1`. If your ordinary host also
serves a network, apply the provided local-assistant middleware before mounting:

```python
from aiify.integration import protect_local_assistant
protect_local_assistant(app, prefixes=("/aiify",))
agent.mount(app)
```

This fragment replaces the recipe's mount call. A different prefix must match
both places. The middleware checks the connection peer; a local reverse proxy
can make remote users appear local, so restrict the assistant paths at that
proxy too. Same-origin checks and a loopback control port do not authenticate
arbitrary users of a network-accessible host page.

Keep ai-ify an optional host dependency when appropriate. Import it only in the
enabled branch; catch a missing dependency with an actionable host message.
Keep assistant files in a dedicated writable folder, and ship maps/prepared
bundles as package data. Attach only the data the task needs; attached files
are copied into the assistant working folder and text may be sent to the provider.

## Verify observable behavior

Use the fake agent and temporary `AIIFY_HOME`, `FAKE_ACP_STORE`, and isolated
provider homes to verify panel wiring, instructions, approvals and cancellation.
Then test real backend effects on disposable inputs, including refusal paths.
Fake-agent replies prove plumbing, not natural-language task competence.

For model evaluations, inspect recorded commands, tool access, inherited context
and actual files/results. Write checks that fail before the task and pass after
the correct backend operation. A reply saying it succeeded is insufficient.
`evaluate --check-tasks` checks the evaluator's assertions without a model.
Use durable host queues for jobs that must survive shutdown; ai-ify's in-memory
scheduled messages are not a background job service.
