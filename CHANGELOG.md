# Changelog

## Unreleased

- Sign in from the panel: when the agent has no subscription login, a "Sign in" card
  runs the vendor's own sign-in in the browser, with no terminal window. The card links
  to the sign-in page and takes the code Claude's page shows, then sends the message
  that was waiting. Neither CLI has to be installed.
- The console button uses the Claude Code or Codex copy the adapter brings when the
  CLI is not installed.
- Without Node.js the panel says so and links to nodejs.org.
- Panel layouts: side (as before), docked (the page makes room), a window that can
  be dragged and resized, and inline in an element the app chooses. The person picks
  side / docked / window in the panel.
- Opacity: thins the panel's background, not its text, so the app shows through.
- `agent.mount(app, inject=True, panel={...})` adds the panel to the app's pages with
  no page edit; `aiify.web.panel_tag()` builds the tag. Options for the accent colour,
  font, starting layout and opacity, and `launcher: none` for apps with their own
  button.

- App context: `When` rules can match what the person typed (`prompt="cost"`, a word
  list, a regex or a function), the model, effort, provider, profile or launch, and
  their text can be a function called for each message with a `Turn` (the text,
  state, settings and launch).
- Launches: `Agent(launches={name: Launch(...)})` gives the app's buttons their own
  way into the assistant, each with its own profile, settings, instructions, rules
  and opening message. Start one with `data-aiify-launch="name"` on any element,
  `aiify.launch(name, data)`, `POST /aiify/api/launch` or `await agent.launch(...)`.

## 0.1.0

First release.

- `Agent`: one app's embedded agent on the Claude or Codex subscription logged in on the
  machine, through the Agent Client Protocol (ACP) adapters; no API key.
- Three control levels: backend actions (functions, registries, dispatchers), named UI
  commands registered by the page, and an automatic tree of the page's controls.
- Profiles with allow / confirm / deny patterns, instructions, and rules that depend on
  app state. Destructive actions show an approval card first.
- FastAPI mount: a drop-in chat panel (model, effort and mode pickers, console hand-off,
  subscription limit bars, Codex account picker) and a local control port reached with
  the `aiify` command.
- `aiify.context`: the usage guide, shipped with the package.
- `aiify.testing.fake_agent`: a scripted stand-in agent for tests.
