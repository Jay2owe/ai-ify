## Backend actions: what the agent may run

Pass `actions=` to `Agent`. Any of these work:

- A dict of plain functions, as is: `{"notes.add": add_note}`. The first line of
  each docstring is the summary the agent sees; parameters come from the signature.
- `aiify.actions.from_functions(funcs, destructive=[...], mutating=[...])` to mark
  which functions change data and which destroy it.
- `aiify.actions.from_dispatch(dispatch, describe, root=...)` for an app that
  already has a JSON action runner (the agentify pattern): `dispatch(name, params)`
  returns `{"ok": ..., "result": ...}` and `describe()` lists the actions.
- `aiify.actions.from_registry(mapping)` for a `{name: spec}` registry whose specs
  carry `fn`, `summary`, `mutates`, `destructive`.
- `aiify.actions.combine(a, b, ...)` to offer several of these as one list, for
  example the app's registry plus a few lookups written for the assistant.

Names are free text; dotted names (`plot.bar`) read well and work with patterns.

## Approval

An action asks the person first when it is marked destructive, when the profile's
`confirm` patterns match it, or when the app itself answers `requires_confirmation`.
With the panel open, a card shows the action, its parameters and "Run it" / "Don't";
it waits 90 seconds, and no answer counts as no. Without an open panel the reply is
`requires_confirmation`, and the agent must ask in its own words before repeating
the command with `--confirm`, which the person then approves as a command.

## Choosing marks

- Read-only (the default): looks things up, changes nothing.
- `mutating`: changes data but is easy to undo or repeat (add, rename, select).
- `destructive`: deletes or overwrites (clear outputs, remove a recording). Mark
  these; the approval card is the only thing between the agent and the data.

Results must be JSON-friendly; ai-ify converts dates, paths, numpy values and
dataclasses, and turns NaN or infinity into null.

## Reuse an existing dispatcher

This complete adapter example reads a backend value without inventing a second
store. In a real host, import its existing dispatcher/describer instead:

```python
from aiify.actions import from_dispatch

def describe(name=None):
    spec = {"name": "count", "summary": "Read note count", "mutates": False,
            "destructive": False, "params": []}
    return {"actions": [spec]} if name is None else spec

def dispatch(name, params, root, confirm=False):
    if name != "count":
        return {"ok": False, "error_type": "unknown_action", "error": "Unknown action"}
    return {"ok": True, "result": {"count": root["count"]},
            "equivalent_script": "print(store['count'])"}

store = {"count": 2}
source = from_dispatch(dispatch, describe, root=store)
assert source.run("count", {})["result"] == {"count": 2}
```

`root` is the backend's existing root/context, passed as the dispatcher's third
positional argument. ai-ify calls `describe()` to list actions and caches that
catalogue. Keep names and safety flags stable for that source's lifetime.
`equivalent_script` is preserved when the dispatcher supplies it; ai-ify does not
invent equivalent scripts for arbitrary functions.

For `from_registry`, specs carry a callable `fn`, summary and safety flags;
optional `coerce` maps parameter names to converters. If the callable's first
argument is `ctx` or `context`, pass `context_factory=lambda: live_context`.
`resolve` can resolve string function names. For asynchronous functions, use a
host wrapper that follows your app's event-loop ownership; these action sources
call synchronous backend functions.

`combine(primary, extras)` uses the first owner when names collide. Validate
parameters and storage paths inside the backend and return evidence of changes.
Inspect required parameters with `source.describe(name)`, then check both the
successful result and an invalid-input response on disposable state.
