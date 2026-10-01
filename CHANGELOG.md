# Changelog

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
