"""Shared controls retain the host's action boundaries and avoid model calls."""
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from aiify import Agent
from aiify.integration import helper_options, protect_local_assistant


def host(tmp_path, **kwargs):
    package = tmp_path / "package"
    package.mkdir()
    (package / "aiify_map.md").write_text("## Overview\nA test app.\n", encoding="utf-8")
    app = FastAPI()

    @app.get("/api/allowed")
    def allowed():
        return {"value": 7}

    @app.get("/private")
    def private():
        return {"secret": 9}

    agent = Agent("helper-control-test", limit_check_every=None,
                  **helper_options(package, env="TEST_AIIFY_OPTIONS", routes=("/api/*",), **kwargs))
    agent.mount(app, prefix="/assistant")
    return app, agent


def test_defaults_and_person_opt_in_are_scoped(tmp_path):
    app, agent = host(tmp_path)
    assert agent.route_source is None
    with TestClient(app) as client:
        assert agent.helpers() == {"how": True, "app_map": True, "routes": False}
        response = client.post("/assistant/api/helpers", json={"routes": True}, headers={"X-Aiify": "1"})
        assert response.status_code == 200 and response.json()["ok"]
        assert agent.route_source.names() == ["route.allowed"]
        assert agent.route_source.run("route.allowed", {})["result"] == {"value": 7}
        assert "route.private" not in agent.route_source.names()
        client.post("/assistant/api/helpers", json={"routes": False}, headers={"X-Aiify": "1"})
        assert not agent.route_source.names()


def test_helper_changes_preserve_running_context_and_guard_requests(tmp_path):
    app, agent = host(tmp_path)
    agent.launch_data = {"file": "pinned.svg"}
    with TestClient(app) as client:
        endpoint = "/assistant/api/helpers"
        assert client.post(endpoint, json={"how": False}).status_code == 403
        assert client.post(endpoint, json={"how": False}, headers={"X-Aiify": "1", "Origin": "https://foreign.test"}).status_code == 403
        for value in ({"routes": ["/private"]}, {"how": "false"}, {"unknown": True}, {}):
            assert client.post(endpoint, json=value, headers={"X-Aiify": "1"}).status_code == 400
        agent.busy = True
        assert client.post(endpoint, json={"how": False}, headers={"X-Aiify": "1"}).json()["code"] == "busy"
        agent.busy = False
        result = client.post(endpoint, json={"how": False, "app_map": False}, headers={"X-Aiify": "1"}).json()
        assert result["next_chat"] and not agent.how_enabled
        assert agent.launch_data == {"file": "pinned.svg"}
        assert agent.helper_availability()["app_map"]
        assert client.post(endpoint, json={"prepared": True}, headers={"X-Aiify": "1"}).json()["code"] == "not_supported"


def test_startup_defaults_are_independently_configurable(tmp_path, monkeypatch):
    monkeypatch.setenv("TEST_AIIFY_OPTIONS", '{"how":false,"app_map":false,"routes":true}')
    _, agent = host(tmp_path)
    assert agent.helpers() == {"how": False, "app_map": False, "routes": True}
    assert agent.helper_availability()["app_map"]
    agent.set_helpers(app_map=True)
    assert agent.helpers()["app_map"]


def test_incomplete_optional_bundle_does_not_block_the_chat_shell(tmp_path):
    package = tmp_path / 'package'
    bundle = package / 'aiify_prepared'
    bundle.mkdir(parents=True)
    (bundle / 'actions.py').write_text('# Being prepared', encoding='utf-8')
    options = helper_options(package, env='TEST_AIIFY_OPTIONS')
    assert options['prepared'] is None
    agent = Agent('incomplete-helper-test', **options)
    agent.mount(FastAPI(), prefix='/assistant')
    assert agent.prepared is None
    # Presence is only the eligibility check: a corrupt receipt is not trusted.
    (bundle / 'verification.json').write_text('{}', encoding='utf-8')
    options = helper_options(package, env='TEST_AIIFY_OPTIONS')
    assert options['prepared'] == bundle
    with pytest.raises((OSError, ValueError)):
        Agent('invalid-helper-test', **options).mount(FastAPI(), prefix='/assistant')


@pytest.mark.parametrize("value", ['[]', '{"how":1}', '{"model":"x"}', '{"routes":true}'])
def test_invalid_configuration_fails_before_a_model_starts(tmp_path, monkeypatch, value):
    monkeypatch.setenv("TEST_AIIFY_OPTIONS", value)
    with pytest.raises(ValueError):
        helper_options(tmp_path, env="TEST_AIIFY_OPTIONS")


def test_filesystem_assistant_is_local_while_host_api_remains_available(tmp_path):
    app, agent = host(tmp_path)
    protect_local_assistant(app, prefixes=("/assistant",))
    with TestClient(app, client=("192.0.2.10", 40000)) as remote:
        assert remote.get("/api/allowed").json() == {"value": 7}
        assert remote.get("/assistant/api/info").status_code == 403
        assert remote.post("/assistant/api/helpers", json={"routes": True}, headers={"X-Aiify": "1"}).status_code == 403
        from starlette.websockets import WebSocketDisconnect
        with pytest.raises(WebSocketDisconnect):
            with remote.websocket_connect("/assistant/ws"):
                pass
    with TestClient(app, client=("127.0.0.1", 40000)) as local:
        assert local.get("/assistant/api/info").status_code == 200
