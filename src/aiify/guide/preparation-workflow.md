# App preparation workflow

You are preparing backend actions for an assistant embedded in an app using
ai-ify. Inspect the supplied source snapshot. Return a JSON object containing
the generated files; change no files and do not execute app operations.

1. Identify the app's real backend, public interfaces, state ownership and
   existing actions. Prefer reusing existing actions and routes. Identify useful
   missing operations and support each with a source-file location. Do not expose
   arbitrary execution, shell commands, file access or internal maintenance merely
   because a function exists. State unsupported operations in the analysis.
2. Design stable action names, parameter signatures and ownership of outputs.
   Explain whether each action reads, changes or destroys data. Require explicit
   destructive marking for deletion, replacement or irreversible operations.
3. Write synchronous Python wrappers in actions.py over the app's real backend.
   Keep imports inside functions where possible. Do not create a separate data
   model, duplicate algorithms, import the chat engine or start a control server.
   Do not use runtime exec/eval or shell=True. Return useful Python values;
   ai-ify supplies serialization, errors, descriptions and approval handling.
   Wrappers using live state must access the host app's actual state. Describe
   where the developer supplies it. Never manufacture a second app instance.
   When wrappers need the live app, actions.py defines exactly `bind(app)`, which
   load_prepared(path, app=app) calls once with the host's app object. Use this
   name and signature only; derive anything else (a scratch folder, a store) from
   the app or give it a safe default, so hosts need no bundle-specific code.
4. Write TEST.md BEFORE designing test_actions.py: list workflows, expected
   outputs, required real dependencies and the test function covering each action.
5. Write pytest tests in test_actions.py that call wrappers and check real app
   state/results. Import actions.py using its path under AIIFY_PREPARED_DIR
   (importlib.util.spec_from_file_location is appropriate). Use pytest tmp_path
   or AIIFY_VERIFY_DIR for disposable data. Never mutate existing user data.
   Do not mock or skip the target backend. Missing dependencies must fail clearly.
   Check useful output content, not just file existence or process exit status.
   Use top-level test_ functions; do not define duplicate function names. Include
   failure/invalid-argument tests and destructive-action coverage where applicable.
   When the app ships demo or example data, put it through each wrapper by the
   same route a person's data takes (import it, then use the wrapper), and feed
   any file or spec a wrapper returns back into the app's own reader to prove it
   opens. Names, extensions and formats differ between such data and test files.
   When all useful operations are already exposed, actions may be empty, but
   still include tests of the existing real backend and an explanatory guide.
6. Write guide.md with the supported actions, exact parameters, multi-step task
   examples, prerequisites, limits, data/state ownership and embedding instructions.
   Describe adding Prepared.actions to existing actions with aiify.actions.combine,
   and passing the prepared bundle as guide=. Do not claim tests have passed.

Return ONLY JSON (an optional ```json fence is accepted), with exactly these
fields. Newlines inside Python and Markdown strings must be JSON-escaped.

{
  "schema_version": 1,
  "analysis": "Backend discovered, controls reused, missing operations and limits",
  "actions": [
    {
      "name": "domain.operation",
      "function": "wrapper_function",
      "summary": "What the operation does",
      "mutates": false,
      "destructive": false,
      "evidence": ["backend.py:42"],
      "tests": ["test_operation"]
    }
  ],
  "files": {
    "actions.py": "Python module contents",
    "test_actions.py": "Pytest module contents",
    "guide.md": "App usage guidance",
    "TEST.md": "Test plan and required backend dependencies"
  }
}

Action names already present in the inventory must not be repeated. Every action
must reference a function in actions.py and at least one test in test_actions.py.
Read source evidence rather than guessing APIs or pretending unsupported features
work. The tool validates the bundle and runs verification separately.

Workflow adapted from CLI-Anything's discover/build/test/document methodology:
https://github.com/HKUDS/CLI-Anything/blob/main/cli-anything-plugin/HARNESS.md
