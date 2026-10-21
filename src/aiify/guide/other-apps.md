## Apps without FastAPI

`agent.mount(app)` needs a FastAPI (or Starlette-compatible) app; it ties the
agent to the app's start and stop. Other apps can still offer backend actions to
outside agents through the control port:

```python
agent = Agent(app="myqtapp", actions=registry)
agent.start_background()        # the control port on its own thread
...
agent.stop_background()         # when the app quits
```

`aiify --app myqtapp action.list` then works from any terminal or agent session.
There is no in-app chat panel for non-web apps yet.

## Turning the assistant on and off

Keep ai-ify optional in an app that is published for others: import it only when
a setting or environment variable asks for it, and catch `ImportError`. For
example Circadian Workbench mounts it only when `CIRCADIAN_WORKBENCH_AI=1` and
the `ai` extra is installed, and its frozen Windows build excludes `aiify` and `acp`.

## Agent start-up

The agent process starts when a panel connects (so the pickers fill and the first
reply is quicker), or at app start with `Agent(..., prewarm=True)`. It runs in
the app's work folder and is stopped, with any child processes, when the app stops.

## A complete non-web lifecycle example

This example starts only the local action control port, reads through the same
command a caller would use, and then stops. No real agent is started:

```python
import io
import json
import os
from tempfile import TemporaryDirectory
from aiify import Agent
from aiify.cli import main

with TemporaryDirectory() as folder:
    os.environ["AIIFY_HOME"] = folder
    agent = Agent("desktop-example", actions={"status.read": lambda: {"ready": True}})
    agent.start_background()
    try:
        output = io.StringIO()
        code = main(["--app", "desktop-example", "action.run", "status.read"], out=output)
        reply = json.loads(output.getvalue())
        assert code == 0 and reply["result"] == {"ready": True}
    finally:
        agent.stop_background()
```

Start once and stop on every exit path. For actual widgets, marshal reads and
writes onto the GUI's owning thread. A worker-thread action must not directly
touch Qt/Tk widgets. Use `programmatic` for async questions and event delivery.

## Optional host installation

In your host's metadata, an optional dependency can be
`ai = ["ai-ify[web]>=0.5.0"]` (choose a tested range for your release).
This fragment assumes `app` exists and replaces an unconditional mount:

```python
import os

if os.environ.get("MYAPP_AI") == "1":
    try:
        from aiify import Agent
    except ImportError as exc:
        raise RuntimeError('Install the host app with its [ai] extra to enable the assistant') from exc
    agent = Agent("myapp")
    agent.mount(app, inject=True)
```

With the setting absent, this branch imports no ai-ify code and adds no panel.
For a frozen distribution deliberately omitting the assistant, exclude `aiify`
and `acp` in its build configuration. For one that includes it, bundle its
static files and keep a writable assistant working folder outside the install.
