# Changelog

## 0.3.0

- The app's web routes become actions (`route.<name>`) with no code: reading routes
  run freely, others ask first. `Agent(routes=...)` narrows or turns this off.
- `aiify how "plain question"`: a local search over actions, routes, pages, page
  commands, controls, every guide topic, the README, app notes and the app map, each
  hit saying how to use it.
- The app map: `python -m aiify.appmap build module:app` has the developer's agent
  read the source and write `aiify_map.md` (screens, how-to tasks, terms); the running
  agent finds it in the package and `check` says when the source has moved on.

## 0.2.0

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
- Hooks: `before_send(turn)` can let a message through, rewrite it, or answer it from
  the app (`Answer`) without asking the agent; `after_reply(turn, reply)` sees each
  reply.
- Suggested prompts as buttons in an empty chat (`suggestions=` on the agent, a
  profile or a launch).
- `lock=` and `limit=` on profiles and launches hide pickers or narrow their values.
- `await agent.ask(prompt, schema=...)`: a one-off question from the app's code in a
  separate conversation, with the reply checked against a JSON Schema or pydantic model.
- Attachments: `agent.attach(...)`, `aiify.attach(...)` and launches with files;
  with `attachments=True` the person can attach, paste or drop files.
- App notes (`notes=True`): kept across chats, read at the start of each, added to by
  the agent when asked to remember something.
- Queued messages (`queue=True`, Tab while the agent answers) and scheduled ones
  (`schedule=True`, "Later").

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
