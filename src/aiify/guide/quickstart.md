## A notes app with an assistant, in one file

This example runs without any subscription: `engine_argv` swaps the real agent
for ai-ify's scripted test agent. Remove that line to use Claude.

```python
# notes_app.py  -  pip install "ai-ify[web]"; python notes_app.py
import sys
import uvicorn
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from aiify import Agent, Profile
from aiify.actions import from_functions

NOTES = []

def add_note(text: str):
    """Add a note."""
    NOTES.append(text)
    return {"count": len(NOTES)}

def clear_notes():
    """Delete every note."""
    NOTES.clear()
    return "cleared"

fake = [sys.executable, "-m", "aiify.testing.fake_agent"]
agent = Agent(
    app="notes",
    actions=from_functions({"notes.add": add_note, "notes.clear": clear_notes},
                           destructive=["notes.clear"], mutating=["notes.add"]),
    guide="A list of short text notes.",
    profiles={"default": Profile(provider="claude")},
    state=lambda: {"notes": NOTES},
    engine_argv={"claude": fake},          # remove to use the real Claude
)
app = FastAPI()

@app.get("/", response_class=HTMLResponse)
def page():
    return '<h1>Notes</h1><script src="/aiify/panel.js" defer></script>'

agent.mount(app)
uvicorn.run(app, host="127.0.0.1", port=8770)
```

## Check that it works

1. Open http://127.0.0.1:8770/ and click the round "AI" button: the panel opens
   and its status line reads "ready". Type "hi": the scripted agent answers
   "hello from fake".
2. In a second terminal: `aiify --app notes action.run notes.add text=hello`
   prints `{"ok": true, ... "result": {"count": 1}}`.
3. `aiify --app notes action.run notes.clear` with the panel open shows a
   "Run notes.clear?" card in the panel; "Don't" makes the command print
   `"code": "denied"`. With no panel open it prints `"code": "requires_confirmation"`.

The real agent does the same through these commands when the person asks it to.