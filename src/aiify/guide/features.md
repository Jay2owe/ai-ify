# All features and configuration options

This catalogue covers the public embedding controls. Read a named topic with
`context.read(topic)` or `python -m aiify.context topic`; every topic is also
included in the portable `README_AI.md` and `aiify_context.json` files.

## Choose what the assistant should do

| Feature | How to enable or use it | Result and relevant limit | Detailed topic |
|---|---|---|---|
| Embedded chat | `Agent(...).mount(app)` and a panel tag, or `inject=True` | Streaming chat tied to the web app lifecycle | `integration` |
| Backend functions | `actions=from_functions(...)` | Described callable tools; mark writes and deletes explicitly | `actions` |
| Existing dispatcher or registry | `from_dispatch(...)`, `from_registry(...)`, `combine(...)` | Reuses the host's calculation and storage code | `actions` |
| Approval cards | Destructive action flag or profile `confirm` patterns | Waits for the person; declining prevents execution | `actions` |
| Named page commands | `window.aiify.registerTool({...})` | Calls a page function; needs a connected page | `page-control` |
| Automatic page controls | `aiify ui tree`, then click/fill/select/read | Visible controls, with stable names via `data-agent` | `page-control` |
| Page state | `window.aiify.setState(callback)` | Merged with Python state for each message | `page-control` |
| Claude or Codex | `Profile(provider="claude")` or `"codex"` | Uses subscription sign-in and adapter-supplied choices | `models` |
| Profiles and permissions | `profiles={name: Profile(...)}` | Named roles with action allow/deny/confirm patterns | `profiles` |
| App guidance and current facts | `guide`, `instructions`, `state` | Orientation once per chat; state every message | `context` |
| Conditional instructions | `When(...)` in `rules` | Adds matching guidance to each turn | `context` |
| Contextual launch buttons | `Launch(...)` and `aiify.launch(name, data)` | Starts a task with its own context, suggestions and settings | `context` |
| Before/after message hooks | `before_send`, `after_reply` | Rewrite, answer locally, or observe completed replies | `chat-options` |
| Suggested prompts | `suggestions` on Agent/Profile/Launch | At most eight choices; launch overrides profile, then app | `chat-options` |
| Picker restrictions | Profile/Launch `lock` and `limit` | Constrains changes through the panel; host code remains authoritative | `chat-options` |
| Questions from code | `await agent.ask(prompt, schema=...)` | Separate hidden conversation, optional structured result | `programmatic` |
| Attachments | `agent.attach(...)`; `attachments=True` for person-facing controls | Saved copies, at most 10 MiB per file, sent with next message | `chat-options` |
| Persistent notes | `notes=True` or a path | App notes survive new chats and restarts | `chat-options` |
| Queue and scheduling | `queue=True`, `schedule=True` | Sequential messages; pending work lasts only while the app runs | `chat-options` |
| Assistant messages | `MessageHub(...).mailbox(...)`, supplied as `messaging` | Durable mail and references; delivery starts no model turn | `messaging` |
| Local guidance search | `how=True` (default); `aiify how "question"` | Searches available instructions, actions and controls locally | `discovery` |
| App map | Ship `aiify_map.md`; `app_map="auto"` | Source-based multi-step guide; generate before shipping | `discovery` |
| Prepared backend shortcuts | Supply a reviewed, verified `prepared` bundle | Adds actions and guidance; never generated during normal chats | `preparation` |
| Web routes as tools | `routes=["/api/samples*"]` | Selected host routes; non-GET methods require approval | `discovery` |
| Helper switches | `helper_defaults`, `set_helpers`, panel Controls | Enables supplied/permitted helpers for the next chat | `discovery` |
| Panel layout and appearance | `panel={...}`, `panel_tag(...)`, script attributes | Overlay, dock, float or inline; browser remembers view choices | `panel-look` |
| Existing host runner | Serve panel assets and call `aiify.bindHost(...)` | Uses host conversations, queue and approvals | `host-runner` |
| Non-web integration | `start_background()` / `stop_background()` | Local backend control port without a desktop panel | `other-apps` |
| Terminal conversation | Panel Console / `agent.open_console()` | Resumes the provider conversation | `console-and-limits` |
| Usage and accounts | `limit_warning`, `limit_check_every`, `codex_accounts` | Provider usage readings and optional Codex account picker | `console-and-limits` |
| Fake-agent tests | `engine_argv` or `AIIFY_ENGINE_COMMAND` | Tests wiring without signing in or spending model usage | `testing` |
| Task evaluations | `python -m aiify.evaluate ...` | Checked outputs and helper comparisons on disposable data | `evaluate` |
| Offline package knowledge | `context.read`, `context.search`, portable artifacts | Read-only; no server, backend construction or model request | `overview` |

## Every Agent constructor option

Defaults below describe this installed version. Omit an option to retain its
live default; configure it when your app requires different behavior.

| Option | Default | Meaning and how to use it |
|---|---|---|
| `app` | Required | Stable app name, e.g. `"notes"`; used to discover the running instance |
| `actions` | `None` | Callables, registry, dispatcher adapter or action source; see `actions` |
| `guide` | `""` | Text, zero-argument callable or reader object; orientation sent on first message |
| `profiles` | One default `Profile()` | Mapping from role names to profiles |
| `profile` | First configured profile | Initial profile name; use a key present in `profiles` |
| `state` | `None` | Zero-argument callable returning current JSON-friendly facts |
| `rules` | `()` | Sequence of `When` rules evaluated for each message |
| `instructions` | `""` | Text or function of state; included in first-message orientation |
| `cwd` | `None` | Explicit assistant working folder; otherwise per-user `work/<app>` |
| `prewarm` | `False` | Start the adapter at app start rather than waiting for a connected panel |
| `auto_allow_app_command` | `True` | Automatically approves recognized plain commands for this app; `False` disables that convenience |
| `command` | Generated Python command | Override the command advertised to the agent only when your host requires a custom launcher |
| `engine_argv` | Empty mapping | Provider-to-argument-list adapter overrides; useful for the fake agent |
| `limit_warning` | `0.9` | Usage bar warning fraction, e.g. `0.8` for 80%; not a hard usage stop |
| `codex_accounts` | `"auto"` | Auto-detect supported saved accounts; `None` hides account switching |
| `limit_check_every` | `600` seconds | Minimum interval for extra Claude usage checks; `None` disables those checks |
| `launches` | `None` | Mapping from button names to `Launch` configurations |
| `before_send` | `None` | Sync/async function of `Turn`; can answer, rewrite or reject a message |
| `after_reply` | `None` | Sync/async function of `Turn, AgentReply`; observe results |
| `suggestions` | `()` | Texts, label/text dictionaries, or function of `Turn` returning them |
| `queue` | `False` | Show controls for messages to run after the active reply |
| `schedule` | `False` | Show controls for later messages; requires the app to stay running |
| `attachments` | `False` | Show user attachment controls; app code may still attach explicitly |
| `notes` | `False` | `True` for default persistent notes file, or an explicit file path |
| `routes` | `False` | `True` for all eligible routes, or selected path patterns; prefer selected paths |
| `app_map` | `"auto"` | Find a shipped map, use an explicit path, or `None` to disable |
| `how` | `True` | Enable local searchable guidance |
| `prepared` | `None` | Verified bundle directory or `Prepared` object; no automatic bundle discovery |
| `route_options` | `()` | Path patterns the host permits a person to enable through Controls |
| `helper_defaults` | `None` | Initial boolean switches for `how`, `app_map`, `prepared`, `routes` |
| `messaging` | `None` | Mailbox from a `MessageHub`; enables Messages and mailbox operations |
| `user_mcp` | `False` | Also start the MCP servers in the person's own Claude/Codex settings, and Claude's claude.ai connectors such as Gmail (each local server is a 50-70 MB process per conversation) |

`AIIFY_ENGINE_COMMAND` is a JSON argument list overriding adapter launches.
`AIIFY_HOME` changes per-user storage. `FAKE_ACP_STORE` selects a fake-agent
session file for tests. See `setup` and `testing` for their use.

## Profile, Launch and When options

`Profile` defines a selectable role. `Launch` defines the setup for one app
button. `When` adds instructions when all specified conditions match.

| Class | Options | Usage |
|---|---|---|
| `Profile` | `provider`, `model`, `effort`, `mode` | Provider is Claude by default; `None` for the other settings preserves adapter defaults |
| `Profile` | `allow`, `confirm`, `deny` | Action-name glob patterns: allowed by default, destructive always asks; deny wins |
| `Profile` | `instructions`, `rules`, `label` | First-message guidance, per-message conditional rules, picker label |
| `Profile` | `suggestions`, `lock`, `limit` | Empty by default; customize prompts and panel pickers |
| `Launch` | `label`, `profile`, `model`, `effort`, `mode` | Optional label, existing profile key and adapter settings for this task |
| `Launch` | `instructions`, `rules`, `message` | Text or `Turn` callbacks for instructions/message; sequence of conditional rules |
| `Launch` | `new_chat` | `True` starts a fresh conversation; `False` adds context to the current one |
| `Launch` | `suggestions`, `lock`, `limit` | Task-specific picker and prompt controls; read `chat-options` for precedence |
| `When` | `predicate` | Optional function of state; false or raised exception means no match |
| `When` | `prompt` | Word prefix, word list, compiled regular expression or text predicate |
| `When` | `provider`, `model`, `effort`, `profile`, `launch` | Optional glob pattern or list; every supplied condition must match |
| `When` | `add_instructions`, `name` | Text or `Turn` callback, plus a diagnostic name for errors |

Picker `lock` accepts `profile`, `provider`, `model`, `effort`, `mode`.
Picker `limit` accepts only `model`, `effort`, `mode`, with allowed glob patterns.
These are panel controls, not restrictions on the host's own configuration calls.
Action profiles govern backend action execution; they do not sandbox the vendor
agent's other tools or automatically authorize/forbid every page interaction.
Read `best-practices` before treating a profile as an access boundary.

## Mounting and host-side helpers

- `agent.mount(app, prefix="/aiify", inject=False, panel=None)` ties start/stop
  to the web server. A changed `prefix` must also appear in your panel tag.
- `aiify.web.panel_tag(prefix="/aiify", **options)` creates the script tag;
  `panel-look` lists appearance options. `data-bridge="false"` disables page
  controls for a chat-only page.
- `aiify.integration.helper_options(package_path, env="MYAPP_AIIFY_OPTIONS",
  routes=("/api/samples*",), overrides=None)` returns Agent keyword arguments
  for fixed packaged assets and permitted paths. The environment value must be
  a JSON object of boolean helper switches. `overrides` wins over that object.
- `aiify.integration.protect_local_assistant(app, prefixes=("/aiify",))`
  restricts assistant HTTP/WebSocket paths to loopback clients while retaining
  the host's own rules elsewhere. Read `best-practices` for proxy limitations.
- `aiify.panel.static_asset("panel.js")` / `static_asset("panel.css")` return
  shipped asset paths for a host that owns its own runner. Use `host-runner` for
  the request and event contract.

For messages, events, reset, cancellation, structured questions and configuration
from Python code, read `programmatic`.
