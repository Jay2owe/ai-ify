## What has to be installed

- Python 3.10 or newer. `pip install "ai-ify[web]"` for the chat panel (FastAPI,
  uvicorn and a websocket library); plain `pip install ai-ify` gives the control
  port and the `aiify` command only.
- Node.js with `npx` on the PATH. The first chat downloads the agent adapter
  (`@agentclientprotocol/claude-agent-acp` or `@agentclientprotocol/codex-acp`);
  later starts reuse npm's cache.
- A signed-in subscription: run `claude` once and log in for Claude, or
  `codex login` for Codex. ai-ify uses that login; it never asks for an API key.
- Optional: `codex-profiles` (npm) if several Codex accounts are saved; the panel
  then offers an account picker.

## Where ai-ify keeps files

Everything goes in one per-user folder, never in the app's own folder:
`%LOCALAPPDATA%\ai-ify` on Windows, `~/.local/share/ai-ify` elsewhere, or the
folder named by the `AIIFY_HOME` environment variable.

- `apps/`: one small file per running app (its port and a random token), removed
  when the app stops. The `aiify` command reads these to find apps.
- `work/<app>/`: the agent's working folder for that app. The agent starts there,
  not in the app's data folder.

## Safety defaults

- The control port listens on 127.0.0.1 only and needs the token from the app's file.
- The panel's web routes accept only same-origin requests carrying an `X-Aiify: 1` header.
- Importing `aiify` starts nothing; an agent process starts only when a panel opens
  (or the app asks for it) and stops with the app.