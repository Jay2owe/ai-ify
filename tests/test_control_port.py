import asyncio
import json
import os
import sys

import pytest

from aiify.control_port import ControlPort, list_apps
from aiify.protocol import AiifyError, Reply, registry_dir


async def _exchange(port: ControlPort, lines: list[str]) -> list[dict]:
    reader, writer = await asyncio.open_connection("127.0.0.1", port.port)
    out = []
    for line in lines:
        writer.write((line + "\n").encode())
        await writer.drain()
        out.append(json.loads(await reader.readline()))
    writer.close()
    return out


def _req(port, **kw):
    return json.dumps({"token": port.token, **kw})


def test_round_trip_and_errors():
    async def main():
        port = ControlPort("t")

        async def boom(req):
            raise RuntimeError("kaput")

        async def confirm(req):
            raise AiifyError("requires_confirmation", "ask first", requires_confirmation=True)

        async def changed(req):
            return Reply({"x": float("nan")}, {"screen_changed": True})

        port.register("boom", boom)
        port.register("confirm", confirm)
        port.register("changed", changed)
        await port.start()
        try:
            replies = await _exchange(port, [
                _req(port, id=1, op="ping"),
                json.dumps({"token": "wrong", "id": 2, "op": "ping"}),
                "this is not json",
                _req(port, id=4, op="nope"),
                _req(port, id=5, op="boom"),
                _req(port, id=6, op="confirm"),
                _req(port, id=7, op="changed"),
                _req(port, id=8, op="ping", protocol=99),
                _req(port, id=9, op=5),
                _req(port, id=10, op="describe"),
            ])
        finally:
            await port.stop()
        return replies

    r = asyncio.run(main())
    assert r[0]["ok"] and r[0]["id"] == 1 and r[0]["result"]["app"] == "t"
    assert r[1]["code"] == "bad_token"
    assert r[2]["code"] == "invalid"
    assert r[3]["code"] == "unknown_op"
    assert r[4]["code"] == "failed" and "kaput" in r[4]["error"]
    assert r[5]["code"] == "requires_confirmation" and r[5]["requires_confirmation"] is True
    assert r[6]["ok"] and r[6]["result"] == {"x": None} and r[6]["screen_changed"] is True
    assert r[7]["code"] == "invalid"
    assert r[8]["code"] == "invalid"
    assert r[9]["ok"] and "ping" in r[9]["result"]["ops"] and r[9]["result"]["ui_attached"] is False


def test_describe_levels():
    async def main():
        port = ControlPort("t")
        port.describer("actions", lambda: [{"name": "a"}])
        port.ui_attached = lambda: True
        await port.start()
        try:
            return await port.handle_request({"token": port.token, "op": "describe"})
        finally:
            await port.stop()

    res = asyncio.run(main())["result"]
    assert res["levels"]["actions"] == [{"name": "a"}]
    assert res["ui_attached"] is True


def test_registry_file_lifecycle():
    async def main():
        port = ControlPort("life")
        await port.start()
        listed = list_apps()
        path = port._file
        await port.stop()
        return listed, path

    listed, path = asyncio.run(main())
    assert [a["app"] for a in listed] == ["life"]
    assert listed[0]["pid"] == os.getpid()
    assert not path.exists()
    assert list_apps() == []


def test_stale_registry_file_is_removed():
    d = registry_dir()
    d.mkdir(parents=True)
    stale = d / "gone-999999.json"
    stale.write_text(json.dumps({"app": "gone", "pid": 999999, "port": 1, "token": "x"}))
    assert list_apps() == []
    assert not stale.exists()


@pytest.mark.skipif(sys.platform != "win32", reason="Windows process access rules")
def test_process_we_may_not_open_counts_as_alive(monkeypatch):
    # Codex's sandbox may not open the app's process; deleting its registry file
    # then hid the app from every agent.
    import ctypes
    from aiify.control_port import pid_alive

    class Kernel32:
        def OpenProcess(self, *a):
            return 0
    monkeypatch.setattr(ctypes, "WinDLL", lambda *a, **k: Kernel32())
    monkeypatch.setattr(ctypes, "get_last_error", lambda: 5)        # access denied
    assert pid_alive(1234)
    monkeypatch.setattr(ctypes, "get_last_error", lambda: 87)       # no such process
    assert not pid_alive(1234)


def test_refuses_non_local_bind():
    try:
        ControlPort("t", host="0.0.0.0")
    except ValueError:
        return
    raise AssertionError("bound to all interfaces")
