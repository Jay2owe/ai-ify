# Circadian Workbench integration

The first app to embed ai-ify (not yet in a released Circadian Workbench version).
The assistant is optional and stays off unless both
of these are true:

- the `ai` extra is installed (`pip install circadian-workbench[ai]`, which pulls `ai-ify[web]`)
- the environment variable `CIRCADIAN_WORKBENCH_AI` is `1`, `true`, `yes` or `on`

When either is missing, Circadian Workbench imports nothing from ai-ify and behaves
exactly as before; the frozen Windows build excludes `aiify` and `acp`.

## Files changed in Circadian Workbench

| File | Change |
|---|---|
| `src/circadian_workbench/ai_assistant.py` | NEW. Builds the `Agent` (app name `circadian`): the action registry plus a `workbench.recordings` lookup, Circadian Workbench instructions, two profiles (`assistant` asks before `clear_*`, `*remove*`, `*delete*`; `look-only` allows only non-changing actions), page-state rules, and `inject()` that adds the panel scripts to the page. |
| `src/circadian_workbench/static/ai_commands.js` | NEW. Page commands `show_view`, `open_recording`, `set_temporal_mode`, and the on-screen state (home visible, view, scope, temporal mode, active and open recordings, whether a result exists). |
| `src/circadian_workbench/api.py` | Calls `ai_assistant.install(app)` after the security middleware; `index()` passes the page through `ai_assistant.inject()`. |
| `src/circadian_workbench/static/index.html` | Stable `data-agent` names on key buttons: `import-files`, `import-folder`, `run-batch-analysis`, `figure-workspace`, `export-bundle`, `export-actogram`. |
| `src/circadian_workbench/registry_coverage.py` | Lists `ai_assistant` as a non-science module so `discover` stays clean. |
| `pyproject.toml` | `ai = ["ai-ify[web]>=0.1"]` extra. |
| `packaging/circadian-workbench.spec` | Excludes `aiify` and `acp` from the frozen build. |
| `tests/e2e/test_ai_assistant.py` | NEW. Runs the app with the assistant on and ai-ify's fake agent in Edge: panel present, page commands listed, `workbench.recordings` returns the demo, `show_view` switches the view, the control tree leads with the named Figure button, `clear_output` shows an approval card and "Don't" refuses it, and a chat message carries the Circadian Workbench instructions and state. Skipped when ai-ify is not installed. |

## Checks run

- Without ai-ify: focused tests 339 passed, 5 skipped; the blocked-import check and
  `doctor` were clean (84 actions).
- `tests/e2e/test_ai_assistant.py`: 3 passed with the fake engine.
- Real Claude in Edge: listed the saved recording via `workbench.recordings`, switched to
  the daily view via `show_view` with no prompts, and asked before `clear_output`; the
  refusal left the file in place.
- Circadian Workbench's own desktop server in a hidden pywebview window: the panel
  loaded, the page bridge attached, and `show_view` switched the view.

## Lesson for other apps

The panel needs a websocket library in the app's server; `ai-ify[web]` now depends on
`websockets`, because Circadian Workbench's plain `uvicorn` install had none and the
panel could not connect.
