# Use the shared panel with an existing runner

Use this integration when the host already owns durable conversations, a queue,
reviews or process recovery. The host retains its runner, provider sessions,
instructions, authorisation and approval rules. This is a panel transport, not
an alternative Agent engine; it does not start an Agent, control port or server.

Serve `aiify.panel.static_asset('panel.js')` and `static_asset('panel.css')`
from your existing authenticated server under the same prefix. No FastAPI or
agent engine imports are required for these assets. The accepted asset names are
`panel.js`, `panel.css` and `launch-controls.js`; the host retains responsibility for HTTP authentication.

```html
<div id="task-chat" style="height:65vh"></div>
<script src="/shared-aiify/panel.js" data-transport="host"
        data-layout="inline" data-target="#task-chat" data-launcher="none"></script>
<script>
const chat = aiify.bindHost({
  id: 'task-17', operations: ['send', 'queue'],
  info: {ready: true, title: 'Task agent', features: {queue: true}},
  request: (operation, body) => taskRequest(operation, body),
});
chat.receive({kind: 'user', text: 'Check the example'});
chat.receive({kind: 'text', text: 'The saved answer'});
chat.receive({kind: 'done', by_app: true});
</script>
```

`taskRequest` above is supplied by the host; return `{ok:true, result}` only once
the operation is durably accepted, or `{ok:false,error}` / throw on failure.
Only declared `operations` can be called. Validate them and the selected task
again in the host backend. Do not implement unknown operations by evaluating code.
The panel calls `send` while idle and `queue` while busy if `features.queue` is
true. Queueing is the host's responsibility. Native lifecycle/approval controls
can remain in the host page; they are not auto-approved or remapped.

Optional binding properties: `draft` (initial text), `onDraft(text)` (store
per-conversation drafts), `history` (array of normal panel events). A new binding
replaces the previous one; its `receive(event)` returns false after replacement.
`dispose()` disables that binding and its composer. Failed submissions preserve
text; successful delayed replies cannot clear a newer conversation or new text.
`aiify.element` exposes the panel root for moving the same panel between views.

Send `{kind:'info',info}` to update status and controls; `{kind:'reset'}` to
replace the visible history before replaying events. Tool events use
`{kind:'tool',id,title,detail,status}` and subsequent `tool_update`; user messages
use `user`, streamed answers `text`, errors `error`. End a complete assistant
message with `done, by_app:true`. `info.composer` accepts `disabled`, `label` and
`placeholder`; `info.status` supplies the host's state label. Settings are owned
by the host, so the panel hides its provider/profile settings. New chat and
console buttons appear only when the corresponding operations are declared.

Host transport never opens a websocket or loads the page-control bridge.
Each page contains one panel; use separate frames for simultaneous panels.
Serve both assets from the same package version. Test without a model using
`tests/test_host_panel.py` as an example.

## Native task launch controls

For a host that launches its own Codex or Claude workers, serve
`static_asset('launch-controls.js')` and import `launchControls`. Supply saved
`values`, discovered model/effort/account `options`, and an async `save(change)`
that returns the accepted settings. Await `picker.flush()` before launching;
a failed save refuses launch. Dispose the picker when its task changes.
The picker never calls a model. Claude options use `provider: 'claude'` and
the existing login; native Codex supports saved subscription accounts.

`aiify.native.codex_command(model, effort)` preserves exact settings and native
image tools. `codex_environment(account)` isolates saved-account credentials in
the private ai-ify home without changing the global login. Refreshed credentials
stay in that account home; they are not written back into the profile catalogue.
Account authentication failures must be shown by the host, never silently replaced
with another account. The current login uses the ordinary Codex home.

Before claiming work, call `probe_codex_shell(cwd, env=env)`. It runs one fixed
harmless command through the installed Codex app-server without a model turn,
checks its result and terminates its own process tree. Windows native workers
use the unelevated sandbox implementation with workspace-write permissions.
This is a command-access check, not a provider quota or image-generation test.
