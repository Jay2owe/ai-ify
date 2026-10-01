## Testing an app that embeds ai-ify

Tests should never start Claude or Codex. ai-ify ships a scripted stand-in agent:

- `AIIFY_ENGINE_COMMAND='["python", "-m", "aiify.testing.fake_agent"]'` (a JSON list)
  replaces the adapter command for every agent in the process and its children.
  Alternatively pass `engine_argv={"claude": [...], "codex": [...]}` to `Agent`.
- `FAKE_ACP_STORE=<file>` is where the fake keeps its sessions (use a temp folder).
- `AIIFY_HOME=<temp folder>` keeps the app registry and work folders out of the
  real per-user folder.

The fake agent's replies depend on the message: "echo ..." returns the whole
message it received (useful to check instructions and state reached it),
"permission" asks one permission, "slow" streams until cancelled, "history" says
how many messages the session has had, "/usage" returns a limits report; anything
else answers "hello from fake".

To check the control levels in a browser test, start the app server with these
variables, open the page, then drive it with the `aiify` command:

```python
from aiify.cli import main
import io, json
out = io.StringIO()
code = main(["--app", "notes", "ui.do", "show_view", "view=summary"], out=out)
reply = json.loads(out.getvalue())
```

An action that needs approval shows its card in the page as `#aiify-root .perm`
(inside the panel's shadow root); clicking its "Don't" button makes the command
return `denied`.