## The panel says "disconnected - retrying..."

The page cannot open the websocket at `/aiify/ws`. If the server log shows
"No supported WebSocket library detected", install one: `pip install "ai-ify[web]"`
(it brings `websockets`). If the browser console shows a Content Security Policy
error, add `connect-src 'self'`. Recovery: the status line changes to "ready".

## The status stays at "starting the assistant..." or shows an error

The agent adapter did not start. Check that `npx --version` works in the same
environment the app runs in, and that the subscription is signed in (`claude` or
`codex login` in a terminal). The first start downloads the adapter and can take
a minute. Recovery: the model and effort pickers fill in.

## The agent asks the person to approve every command

Its commands are not plain `aiify` commands for this app: they were wrapped in
other shell code (`if`, pipes, loops), used another app name, or carried
`--confirm`. Plain commands, alone or joined with `;`, run without asking.

## `requires_confirmation` from the command line

The action needs approval and no panel is open to show a card. Ask the person,
then repeat with `--confirm`.

## `no_ui`

No page with the panel is open, so on-screen commands cannot run. Backend actions
still work. Open the app's page (the panel can stay closed).

## `stale_ref`

The page changed after the tree was listed. Run `aiify ui tree` again, or give the
control a `data-agent` name so its ref never changes.

## No limit bars

There is no reading until the first message ends. Claude's full reading comes from
a separate `/usage` check, which needs the adapter to start a second time; it is
skipped when `limit_check_every=None`.

## The account picker is missing

It appears only while Codex is the agent, `codex-profiles` is on the PATH, and
more than one Codex account is saved (`codex-profiles list`).