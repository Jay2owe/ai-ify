## What has to be installed

- Python 3.10 or newer. `pip install "ai-ify[web]"` for the chat panel (FastAPI,
  uvicorn and a websocket library); plain `pip install ai-ify` gives the control
  port and the `aiify` command only.
- Node.js with `npx` on the PATH. The first chat downloads the agent adapter
  (`@agentclientprotocol/claude-agent-acp` or `@agentclientprotocol/codex-acp`);
  later starts reuse npm's cache. To avoid running the package manager on every
  chat opening, install the adapter once with `npm install --global
  @agentclientprotocol/codex-acp` (or `@agentclientprotocol/claude-agent-acp`).
  ai-ify prefers `codex-acp` / `claude-agent-acp` on PATH, checks again for each new
  session, and falls back to npx when absent. Installed adapters update only when
  you rerun the install command; explicit `engine_argv` and `AIIFY_ENGINE_COMMAND`
  still take priority. Each adapter brings its own copy of Claude Code or
  Codex, so neither CLI nor any desktop app has to be installed.
- A Claude or ChatGPT subscription. An existing login (`claude`, or `codex login`) is
  used as it is; otherwise the panel shows a "Sign in" card the first time. ai-ify
  never asks for an API key.
- Optional: `codex-profiles` (npm) if several Codex accounts are saved; the panel
  then offers an account picker.

## Where ai-ify keeps files

By default, assistant registry/work files go in one per-user folder:
`%LOCALAPPDATA%\ai-ify` on Windows, `~/.local/share/ai-ify` elsewhere, or the
folder named by the `AIIFY_HOME` environment variable.

`Agent(cwd=...)` overrides that agent's work folder. An explicit notes path
or messaging hub path uses the location chosen by the host. Keep these paths
writable and separate from installed package resources. A working folder is
not a filesystem sandbox for the provider's other tools.

- `apps/`: one small file per running app (its port and a random token), removed
  when the app stops. The `aiify` command reads these to find apps.
- `work/<app>/`: the agent's working folder for that app. The agent starts there,
  not in the app's data folder.

## Safety defaults

- The control port listens on 127.0.0.1 only and needs the token from the app's file.
- The panel's web routes accept only same-origin requests carrying an `X-Aiify: 1` header.
- Importing `aiify` starts nothing; an agent process starts only when a panel opens
  (or the app asks for it) and stops with the app.
