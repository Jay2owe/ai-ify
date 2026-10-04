## Prepare an app before shipping its assistant

`aiify.prepare` is a developer tool. It uses your Claude or Codex subscription to
inspect source and generate missing actions, usage guidance and real-backend
tests. Its discover/build/test/document workflow is informed by
[CLI-Anything](https://github.com/HKUDS/CLI-Anything/blob/main/cli-anything-plugin/HARNESS.md).
The embedded assistant uses the prepared actions through ai-ify's existing local
control connection.

```bash
python -m aiify.prepare inspect ./myapp
python -m aiify.prepare build ./myapp --out ./prepared-round1 --provider claude
python -m aiify.prepare check ./prepared-round1
python -m aiify.prepare verify ./prepared-round1
```

Use a source folder, or an importable app/Agent/factory such as
`myapp.main:app`. A folder is inspected without importing the app. A module
target imports the module and invokes its factory, so it can inventory already
exposed actions and routes. Use `--source DIR` to choose the source folder for a
module target. Generation copies supported source and docs into a temporary
snapshot, capped at 32 MB; narrow `--source` for larger repositories.

`build` writes a new folder: `actions.py`, `guide.md`, `TEST.md`,
`test_actions.py` and `manifest.json`. The default is `aiify_prepared` inside the
source folder. Existing folders are refused; choose another `--out` for a new
round. The manifest records action names, source evidence, read/change/destructive
flags, test coverage, source/artifact hashes, package version and generation
settings. No actions are executed during generation.

Review the wrappers and their flags. They should call the app's existing backend
and access its actual live state, rather than inventing another app instance.
Use the generated guide to understand prerequisites and operations that remain
unsupported. If the app already exposes everything useful, a bundle can provide
guidance and backend tests without adding actions.

## Verify against the real backend

Install `ai-ify[test]` in the app's development environment. `verify` executes
the generated Python tests using the current Python interpreter, so run it in
the environment containing the real backend and its dependencies. Tests should
use disposable inputs and check actual results. They receive:

- `AIIFY_PREPARED_DIR`: the bundle containing `actions.py`.
- `AIIFY_VERIFY_DIR`: a temporary workspace, removed after the test run.
- `AIIFY_HOME`: an isolated temporary folder for test control ports and notes.

The tool records pytest output and test counts in `verification.json`. Failures,
skips, an empty suite, uncovered actions, changed source or changed artifacts
never pass verification. Compilation and source checks alone are not backend
verification. Passing tests confirm their assertions; the developer still needs
to review whether those assertions cover the intended behaviour.

Edits to wrappers, guidance, test plans or tests require another `verify`.
Changes to action names or flags in the manifest also invalidate the receipt.
`check` reports stale source without importing wrappers or executing tests.
Use `--source DIR` when a checkout has moved. `--timeout SECONDS` limits generation
(default 1800) or verification (default 300).
Use `build --focus "inspect recordings and export results"` to concentrate
generation on the tasks your assistant needs.

## Ship and load the bundle

```python
from pathlib import Path
from aiify import Agent

agent = Agent("myapp", prepared=Path(__file__).parent / "aiify_prepared")
agent.mount(app)
```

The bundle loads when the agent is mounted; a bundle that needs the live app
connects itself through its `bind(app)`.

`load_prepared` requires a successful receipt for the exact shipped bundle.
Loading imports developer-reviewed Python wrappers; it starts no generation
process and does not require the original source checkout. Include every bundle
file, including its receipt, as package data. Tests live alongside the prepared
actions to make their coverage inspectable.

When the app has existing actions, use `combine(existing_actions,
prepared.actions)` from `aiify.actions`, and join `prepared.read()` with the app's
existing guide. Existing actions take precedence when names collide. Generation
refuses duplicates already exposed by a module target; for folder targets, check
names against your own registry when wiring the bundle.

Destructive actions still go through ai-ify's approval cards and profile rules.
Preparation adds no second command runtime and never needs to run in ordinary
user chats.

Try the small backend included in the repository with a folder target of
`examples/preparation_demo`. It summarises numbers and exports a new JSON file;
the generated tests should verify the values and refuse overwrites.

Success check: `verify` prints `Verified.`, and loading the bundle exposes the
actions listed in its manifest.
