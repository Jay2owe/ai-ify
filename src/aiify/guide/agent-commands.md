## The aiify command

Any agent or script on the same computer can drive a running app:

```
aiify apps                                    # running apps with ai-ify
aiify --app NAME describe                     # what the app offers
aiify --app NAME state                        # what it shows now
aiify --app NAME action.list [match=plot.*]
aiify --app NAME action.describe NAME
aiify --app NAME action.run NAME key=value ... [--confirm]
aiify --app NAME ui tree [match=export]
aiify --app NAME ui click REF | ui fill REF VALUE | ui select REF VALUE | ui read REF
aiify --app NAME ui do NAME key=value ...
aiify --app NAME wait [timeout=5]             # until the page changes
```

`python -m aiify` is the same command. Without `--app`, the only running app is
used. Values are read as JSON when they parse (`n=3`, `ids=[1,2]`), else as text.
The reply is printed as JSON with `"ok"`; the exit status is 0 when ok.

The embedded agent is told these commands itself, and its own plain `aiify`
commands for this app run without asking the person each time. Commands joined
with `;` or `&&` are fine; pipes, redirects, other programs, `--confirm` and
`raw` requests are shown to the person to approve.

## Error codes

| code | meaning |
|---|---|
| `denied` | the profile forbids it, or the person said no |
| `requires_confirmation` | needs the person's approval; ask, then repeat with `--confirm` |
| `unknown_action` | no such action; run `action.list` |
| `no_ui` | no page is open, so `ui.*` cannot run |
| `stale_ref` | the page changed; run `ui tree` again |
| `invalid` | malformed request or parameters |
| `timeout` | the app or page did not answer in time |
| `failed` | the action raised an error; the message says what |