# Prepare an app for its embedded assistant

The developer runs preparation once when adding or updating app control. The
assistant uses the resulting actions and guide during ordinary chats.

```bash
python -m aiify.prepare build ./myapp
python -m aiify.prepare verify ./myapp/aiify_prepared
```

Read the files before verification; generated tests execute application code
and should use disposable data. The complete shipped guide is available with
`python -m aiify.context preparation`.

```python
from pathlib import Path
from aiify import Agent
from aiify.prepare import load_prepared

prepared = load_prepared(Path(__file__).parent / "aiify_prepared")
agent = Agent("myapp", actions=prepared.actions, guide=prepared)
agent.mount(app)
```

## Product contract

Preparation inspects source and existing actions, generates thin wrappers over
the app's own backend, documents tasks and plans real-backend tests. It writes a
separate bundle for developer review. Verification runs the generated tests and
records their results; the runtime loads verified bundles explicitly through the
existing action registry and local control connection.

Existing actions and web routes remain the preferred controls. Preparation adds
missing operations rather than generating a competing command-line runtime.
The first implementation supports source folders and importable Python apps;
other software can be wrapped through documented automation interfaces when
those interfaces are evidenced in the supplied source or docs.

## Workflow

```text
inspect source and existing controls
    → generate wrappers, guide and test plan
    → review the files
    → run tests against disposable app data
    → load the verified actions into the app
```

Generation uses the developer's Claude or Codex subscription. It returns file
contents for the preparation tool to validate and write. Verification is a
separate explicit step because generated tests execute application code.
Successful compilation alone never counts as backend verification. Runtime
loading checks the verification record against the shipped files; there is no
agent or source scan during loading.

The bundle has a versioned manifest, source and artifact hashes, provider/model
settings, test coverage by action, and a verification receipt. Existing bundles
are preserved; a new round goes in a new output folder. Source changes invalidate
the developer check. Artifact changes invalidate verification.

## Performance targets

Command help should be available within one second. Loading the preparation
module must import neither a provider adapter nor the application's backend.
Loading a verified bundle should add less than 100 ms for small action modules,
excluding imports owned by the target app. Generation and real-backend testing
report progress and have configurable timeouts.

## Workflow source

The analysis, wrapper generation, test planning, real-backend verification and
agent documentation stages are informed by
[CLI-Anything's methodology](https://github.com/HKUDS/CLI-Anything/blob/main/cli-anything-plugin/HARNESS.md).
This implementation adapts that workflow to ai-ify's existing embedded runtime.
It introduces no CLI-Anything runtime dependency or copied implementation code.

## Validation

Focused preparation, action, discovery, policy and packaged-guide checks passed
(41 tests). The preparation tests cover real-backend state changes, destructive
approval, both provider adapters through the agent protocol, source freshness,
edited bundles, skipped/empty/failing suites and stale bytecode caches.

Real Codex generated a bundle for `examples/preparation_demo` in 230.8 seconds.
The generated suite passed all 16 checks against that backend, including exact
statistics, exported JSON content and refusal to overwrite existing files.
The verified bundle was then loaded into an `Agent`; its summary and export
actions succeeded through the existing local control port and its guide was
available to the assistant. Bundle loading took 16 ms without importing the
provider engine. These are measurements for this small example, not estimates
for arbitrary apps. The generated bundle and receipt are kept in
`internal/preparation-smoke/codex` as a development record.

No software-development skill tune was needed for this implementation.

## Feedback

2026-10-02, agreed direction: “we keep our embedded approach and can also steal
the workflow from this so to be used as part of the developer tools for our
package, that the embedded agent would then later benefit from”.
