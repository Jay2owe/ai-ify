"""Hidden, owned adapter processes for embedded conversations."""
import asyncio
from contextlib import asynccontextmanager, suppress
import subprocess
import sys


@asynccontextmanager
async def spawn_agent_process(client, command, *args, cwd=None, env=None, transport_kwargs=None):
    import acp
    # The ACP SDK's stdio launcher does not expose Windows creation flags.
    # Use its public connection API with an owned hidden transport on Windows.
    if sys.platform != 'win32':
        async with acp.spawn_agent_process(client, command, *args, cwd=cwd, env=env,
                                          transport_kwargs=transport_kwargs) as value:
            yield value
        return
    proc = await asyncio.create_subprocess_exec(
        command, *args, cwd=cwd, env=env, stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        creationflags=subprocess.CREATE_NO_WINDOW, **(transport_kwargs or {}))
    async def drain_errors():
        # Drain without retaining unbounded or potentially sensitive diagnostics.
        while await proc.stderr.read(65536):
            pass
    drain = asyncio.create_task(drain_errors())
    conn = None
    try:
        conn = acp.connect_to_agent(client, proc.stdin, proc.stdout)
        yield conn, proc
    finally:
        try:
            if conn is not None:
                await conn.close()
        finally:
            proc.stdin.close()
            try:
                await asyncio.wait_for(proc.wait(), timeout=2)
            except asyncio.TimeoutError:
                from .engine import kill_tree
                kill_tree(proc.pid)
                await asyncio.wait_for(proc.wait(), timeout=5)
            finally:
                drain.cancel()
                with suppress(asyncio.CancelledError):
                    await drain
