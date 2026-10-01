# ai-ify message format (protocol 1)

How an agent, or any other program, talks to an app that has ai-ify embedded.
The same format serves web apps (stage 05 of the build plan) and Qt apps (a
later plan); only the last hop to the screen differs.

## Finding a running app

Each app that starts ai-ify writes a registry file and deletes it on shutdown:

```
%LOCALAPPDATA%\ai-ify\apps\<app>-<pid>.json      (Windows)
~/.local/share/ai-ify/apps/<app>-<pid>.json       (elsewhere)
```

```json
{"app": "circadian", "pid": 1234, "port": 51123, "token": "<32 hex>", "protocol": 1,
 "started": "2026-10-01T12:00:00"}
```

The environment variable `AIIFY_HOME` replaces the `ai-ify` folder (tests use
it). A file whose process is gone is stale; readers delete it. The folder is a
local per-user folder, never a synced one.

The port binds `127.0.0.1` only. There are no accounts: whoever can read the
registry file is the person at the keyboard.

## Framing

TCP, UTF-8, one JSON object per line (newline-delimited). A connection may
carry several requests; each gets exactly one reply line, in order. Lines are
limited to 16 MiB.

## Request

```json
{"protocol": 1, "token": "...", "id": 7, "op": "action.run", "name": "plot.bar", "params": {"markers": ["Iba1"]}}
{"protocol": 1, "token": "...", "id": 8, "op": "ui.do", "name": "show_view", "params": {"view": "plots"}}
{"protocol": 1, "token": "...", "id": 9, "op": "ui.click", "target": "export-button"}
```

| Field | Meaning |
|---|---|
| `protocol` | Optional; when present must be `1` |
| `token` | Required; the registry file's token |
| `id` | Optional; echoed in the reply |
| `op` | Required; one of the operations below |
| others | Operation-specific (`name`, `target`, `value`, `params`, `confirm`, `timeout`) |

## Reply

```json
{"id": 9, "ok": true, "result": {...}, "screen_changed": true}
{"id": 9, "ok": false, "code": "no_ui", "error": "no window is attached to this app"}
```

Every reply is strict JSON: non-finite numbers become `null`. A bad request
never closes the port; it gets an error reply.

| Code | When |
|---|---|
| `bad_token` | Token missing or wrong |
| `invalid` | Malformed line, wrong field types, missing required field, bad protocol version |
| `unknown_op` | No such operation (in this app, or not yet available) |
| `unknown_action` | `action.*` named an action the app does not have |
| `denied` | The app's policy does not allow this action for the current profile |
| `requires_confirmation` | Destructive or confirm-listed; ask the person, then repeat with `"confirm": true` |
| `no_ui` | A `ui.*` operation while no window is attached |
| `stale_ref` | A control-tree ref from an older snapshot |
| `not_found` | Target or named command does not exist |
| `not_supported` | This app or display cannot do it (e.g. web `screenshot`) |
| `timeout` | The window did not answer in time |
| `failed` | The action or command raised; `error` carries the message |

## Three levels of control

The agent tries them top-down.

1. **Backend action** (`action.*`) - the app's own action registry, run inside
   the live process. Works with or without a window. Most reliable.
2. **Named UI command** (`ui.do`) - a command the developer registered for the
   screen (switch view, select rows, open a figure). Survives layout changes.
3. **Control tree** (`ui.tree`, `ui.click`, `ui.fill`, ...) - every visible
   control found automatically. Generic fallback; can break when the layout
   changes. Developers make it reliable by naming controls (`data-agent="..."`
   on the web, `objectName` in Qt) and can mark regions the agent must not
   touch (`data-agent="off"`).

## Operations

| Op | Level | Fields | Result |
|---|---|---|---|
| `ping` | - | - | `{"app", "pid", "protocol"}` |
| `describe` | all | - | `{"app", "protocol", "ops", "ui_attached", "levels": {"actions", "ui_commands"}}` |
| `state` | - | - | What the app reports as on screen (an app-defined object), `null` without a state hook |
| `action.list` | 1 | `match` (glob, optional) | `[{"name", "summary", "mutates", "destructive"}]` - names and one-liners only |
| `action.describe` | 1 | `name` | Parameters and flags for one action |
| `action.run` | 1 | `name`, `params`, `confirm` | The action's own result |
| `ui.do` | 2 | `name`, `params` | The command's return value |
| `ui.tree` | 3 | `match` (optional text filter) | `{"snapshot": n, "elements": [{"ref", "role", "label", "value"?}]}` |
| `ui.click` | 3 | `target` | `{"clicked": ref}` |
| `ui.fill` | 3 | `target`, `value` | `{"filled": ref, "value"}` |
| `ui.select` | 3 | `target`, `value` | `{"selected": ref, "value"}` |
| `ui.scroll` | 3 | `target` (optional), `direction` (`up`/`down`) | `{"scrolled": ...}` |
| `ui.read` | 3 | `target` | `{"ref", "role", "label", "value", "text"}` |
| `screenshot` | - | `target` (optional) | `{"path": "<png file>"}` or `not_supported` |
| `wait` | - | `timeout` (seconds, default 10) | `{"changed": bool, "state"}` once the screen changes or the time runs out |

`action.list` keeps replies small on purpose: large apps have hundreds of
actions, so details come from `action.describe`.

### Control-tree refs

`ui.tree` returns refs in the style of Playwright's AI snapshots. Elements the
developer named carry that name as their ref (`export-button`); others get
`e1`, `e2`, ... A numbered ref is valid only for the snapshot it came from:
after any change to the page, using it returns `stale_ref` and the agent asks
for a new tree. Named refs never go stale.

### Confirmation

When an action is destructive, or matches the profile's `confirm` list:

- with a window attached and a chat open, the app shows an approval card and
  the request waits for the person's answer;
- otherwise the reply is `requires_confirmation`, and the agent asks the person
  in chat, then repeats the request with `"confirm": true`.

## Reaching the screen

`ui.*`, `state`, `screenshot` and `wait` are answered by the display, not the
app's backend:

- **Web** - the page's `/aiify/panel.js` loads `/aiify/bridge.js` (skip it with
  `data-bridge="false"` on the script tag), which shares the panel's websocket
  (`/aiify/ws`). The page says `{"type": "bridge.hello", "tools": [...]}`; the
  app then pushes `{"kind": "ui.request", "id", "op", ...}` and the page answers
  `{"type": "ui.reply", "id", "ok", "result" | "code"+"error", "screen_changed"?}`.
  The page also sends `bridge.tools` when its commands change and
  `bridge.changed` (debounced) when the page changes, which ends a `wait`.
  `state` merges the page's `window.aiify.setState(fn)` result (asked for with
  the internal op `ui.state`) over the backend's state hook. The most recently
  opened page answers. Without an open page, `ui.*` and `wait` return `no_ui`
  and `state` returns the backend's state hook alone.
- **Qt** (later plan) - the app marshals the operation onto the GUI thread,
  walks the widget tree by `objectName` / accessible name, and replies.

`screen_changed: true` is added to replies whose operation changed what is on
screen, so the agent knows its refs are now stale.

## Chat events

The chat panel and the engine exchange events over the app's websocket
(`/aiify/ws`). Each is a JSON object with `kind`:

| Kind | Fields |
|---|---|
| `user` | `text` |
| `text` | `text` (a streamed chunk of the reply) |
| `thought` | `text` |
| `tool` | `id`, `title`, `status`, `detail` |
| `tool_update` | `id`, `title`?, `status`?, `detail`? |
| `plan` | `entries: [{text, status}]` |
| `permission` | `id`, `title`, `detail`, `options: [{id, name, kind}]` |
| `permission_done` | `id`, `option` (or `null` when cancelled) |
| `usage` | `usage` (raw, including vendor `_meta`) |
| `info` | `info`: profile, provider, options, session, busy, console, `limits`, `accounts`, `signin` (below) |
| `status` | `text` |
| `ready` | `session`, `options`, `startup` |
| `options` | `options` (the agent changed a setting itself) |
| `error` | `text` |
| `auth_required` | `provider`, `methods: [{id, name, description, type}]` (`type` is `terminal` or `agent`) |
| `signed_in` | `provider` |
| `done` | `stop` (`auth_required` when the message waits for a sign-in), `first_words`, `total`, `waiting_on_you`, `tools` |

`info.limits` is `{warn_at, providers: {claude|codex: [{kind, label, used, resets_at,
resets_in_s, expired, status, warn}]}}`, with `used` in percent (null when only a status
is known). Claude readings come from `usage_update` `_meta["_claude/rateLimit"]` and
from Claude Code's local `/usage` command, run in a separate session after a message
at most every 10 minutes; Codex readings from its session rollouts.
`info.accounts` is `{current, choices: [{id, name}], pending, error}` when the agent
is Codex and codex-profiles has more than one saved account, else null.
`POST /aiify/api/account {id}` switches account now, or after the running message.

`info.signin` is `{provider, methods, waiting}` while the agent is signed out, else
null. Only subscription methods are offered (Claude `claude-ai-login`, Codex
`chat-gpt`), never API-key ones. `POST /aiify/api/signin {method}` starts one
(`method` may be left out when there is one): a `terminal` method opens a window
running the adapter's own login and is watched (Claude's `auth status`) for up to
10 minutes; an `agent` method is run by the adapter, which opens the browser.
`POST /aiify/api/signin {check: true}` checks now. Once signed in, the message that
met "sign in first" is sent again without a second `user` event.

## Command line

```
aiify apps                                  # list running apps
aiify [--app NAME] ping
aiify [--app NAME] describe
aiify [--app NAME] action.list [match=plot.*]
aiify [--app NAME] action.run plot.bar markers='["Iba1"]' [--confirm]
aiify [--app NAME] ui tree
aiify [--app NAME] ui click e12
aiify [--app NAME] ui fill threshold 0.4
aiify [--app NAME] ui do show_view view=plots
aiify [--app NAME] raw '{"op": "state"}'
```

`ui X` is shorthand for `ui.X`, `action X` for `action.X`. The first bare
argument is the `name` (action and `ui.do`) or the `target` (other `ui.*`);
the second is the `value`. `key=value` pairs go into `params` for `action.run`
and `ui.do`, and onto the request itself otherwise; values are read as JSON
when they parse, else as text. Without `--app`, the only running app is used.
Exit status is 0 when `ok` is true, 1 otherwise.
