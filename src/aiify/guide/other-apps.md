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