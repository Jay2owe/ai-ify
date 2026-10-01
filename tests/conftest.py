from __future__ import annotations

import asyncio
import threading

import pytest


@pytest.fixture(autouse=True)
def aiify_home(tmp_path, monkeypatch):
    """Every test gets its own registry and work folders."""
    home = tmp_path / "aiify-home"
    monkeypatch.setenv("AIIFY_HOME", str(home))
    return home


@pytest.fixture(autouse=True)
def no_real_codex(tmp_path, monkeypatch):
    """Limits come from an empty Codex folder and no saved Codex account is touched."""
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "codex-home"))
    monkeypatch.setattr("aiify.accounts.executable", lambda: None)


class LoopThread:
    """An asyncio loop on a background thread, for code that blocks (the CLI)."""

    def __init__(self):
        self.loop = asyncio.new_event_loop()
        self.thread = threading.Thread(target=self.loop.run_forever, daemon=True)
        self.thread.start()

    def run(self, coro, timeout=30):
        return asyncio.run_coroutine_threadsafe(coro, self.loop).result(timeout)

    def close(self):
        self.loop.call_soon_threadsafe(self.loop.stop)
        self.thread.join(5)


@pytest.fixture
def loop_thread():
    lt = LoopThread()
    yield lt
    lt.close()
