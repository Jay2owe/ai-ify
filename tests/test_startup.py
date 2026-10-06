"""The embedded shell must not wait for provider protocol model imports."""
import subprocess
import sys

import pytest


def test_constructing_agent_does_not_import_provider_protocol(tmp_path):
    code = '''
import sys
from aiify import Agent
agent = Agent(app='startup-test', cwd=sys.argv[1], codex_accounts=None)
assert 'acp' not in sys.modules
assert not agent.started and agent.session is None
'''
    result = subprocess.run([sys.executable, '-c', code, str(tmp_path)],
                            capture_output=True, text=True,
                            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    assert result.returncode == 0, result.stderr


@pytest.mark.skipif(sys.platform != 'win32', reason='Windows batch adapters')
def test_batch_adapter_has_no_visible_command_window(tmp_path):
    import asyncio
    import ctypes
    from ctypes import wintypes
    from pathlib import Path
    from aiify.engine import AcpSession
    shim = tmp_path / 'synthetic npm adapter.cmd'
    fake = Path(__file__).with_name('fake_acp_agent.py')
    shim.write_text(f'@"{sys.executable}" "{fake}"\n', encoding='utf-8')

    async def run():
        session = AcpSession('codex', cwd=tmp_path, argv=[str(shim)])
        try:
            await session.start()
            user = ctypes.WinDLL('user32')
            user.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
            user.IsWindowVisible.argtypes = [wintypes.HWND]
            visible = []
            callback = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
            @callback
            def visit(hwnd, _):
                pid = wintypes.DWORD()
                user.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
                if pid.value == session.pid and user.IsWindowVisible(hwnd):
                    visible.append(hwnd)
                return True
            user.EnumWindows(visit, 0)
            assert not visible
            assert (await session.send('hi'))['stop'] == 'end_turn'
        finally:
            await session.close()
    asyncio.run(run())
