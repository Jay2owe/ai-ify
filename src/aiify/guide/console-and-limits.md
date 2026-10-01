## Console

"Console" in the panel opens the same conversation in a terminal (`claude --resume`
or `codex resume`), for long work or for the vendor's own commands. The next
message typed in the panel picks up what was said there. The button is greyed out
until the agent has started (its status line reads "ready").

## Subscription limits

Bars under the pickers show how full each limit of the agent in use is (5-hour,
weekly, and weekly per model where the subscription has one), with reset times.
A bar turns amber at `limit_warning` (default 0.9, i.e. 90%):
`Agent(..., limit_warning=0.8)`.

- Claude readings come from the agent's own reports and from Claude Code's local
  `/usage` command, run in a separate short session after a message at most every
  10 minutes. It uses no tokens. Change the interval with
  `Agent(..., limit_check_every=1800)`, or turn it off with `None`.
- Codex readings come from Codex's own session logs (`$CODEX_HOME/sessions`).

The bars appear after the first message; until then there is no reading.

## Several Codex accounts

When `codex-profiles` is installed and more than one account is saved, the panel
shows an account picker while Codex is the agent. A switch requested during a
reply happens when that reply ends; the next message restarts Codex signed in as
the chosen account and continues the same conversation. Only the active account
is ever asked for its usage. Pass `codex_accounts=None` to hide the picker.