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