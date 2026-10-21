"""Fast installed launch keeps provider choice, overrides and setup fallback."""
import json

import pytest

from aiify import engine


@pytest.mark.parametrize('provider,name', [('codex', 'codex-acp'), ('claude', 'claude-agent-acp')])
def test_installed_adapter_and_removal_are_seen_without_restart(monkeypatch, tmp_path, provider, name):
    monkeypatch.delenv('AIIFY_ENGINE_COMMAND', raising=False)
    found = str(tmp_path / (name + '.cmd'))
    calls = []
    def which(command):
        calls.append(command)
        return found
    monkeypatch.setattr(engine.shutil, 'which', which)
    assert engine.AcpSession(provider, cwd=tmp_path).argv == [found]
    assert calls == [name]
    found = None
    fallback = engine.AcpSession(provider, cwd=tmp_path).argv
    assert fallback == engine.PROVIDERS[provider]['argv']
    fallback.append('changed')
    assert 'changed' not in engine.PROVIDERS[provider]['argv']


def test_explicit_commands_win_without_discovering_or_starting_provider(monkeypatch, tmp_path):
    def forbidden(*args):
        raise AssertionError('Explicit command must not look up a provider')
    monkeypatch.setattr(engine.shutil, 'which', forbidden)
    monkeypatch.setenv('AIIFY_ENGINE_COMMAND', json.dumps(['fixture-env', 'arg']))
    assert engine.AcpSession('codex', cwd=tmp_path).argv == ['fixture-env', 'arg']
    assert engine.AcpSession('codex', cwd=tmp_path, argv=['fixture-explicit']).argv == ['fixture-explicit']
    assert engine.AcpSession('custom', cwd=tmp_path, argv=['custom-engine']).argv == ['custom-engine']
