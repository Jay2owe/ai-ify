"""Developer preparation, backend verification and live action approvals."""
import importlib
import json
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

from aiify import Agent
from aiify import prepare
from aiify.protocol import AiifyError


@pytest.fixture
def backend(tmp_path, monkeypatch):
    root = tmp_path / "prep_backend"
    root.mkdir()
    (root / "__init__.py").write_text("")
    (root / "backend.py").write_text('''STATE = {"value": 1}

def read_value():
    """Read the value currently held by the app."""
    return STATE["value"]

def clear_value():
    """Clear the value in the live app."""
    STATE["value"] = 0
    return STATE["value"]
''', encoding="utf-8")
    monkeypatch.syspath_prepend(str(tmp_path))
    module = importlib.import_module("prep_backend.backend")
    module.STATE["value"] = 1
    yield root, module
    for name in list(sys.modules):
        if name.startswith("prep_backend"):
            del sys.modules[name]


def payload():
    return {"schema_version": 1, "analysis": "The live backend exposes read and clear operations.",
            "actions": [
                {"name": "value.read", "function": "read_value", "summary": "Read the live value",
                 "mutates": False, "destructive": False, "evidence": ["backend.py:3"],
                 "tests": ["test_read"]},
                {"name": "value.clear", "function": "clear_value", "summary": "Clear the live value",
                 "mutates": True, "destructive": True, "evidence": ["backend.py:7"],
                 "tests": ["test_clear"]}],
            "files": {
                "actions.py": '''def read_value():
    from prep_backend.backend import read_value as read
    return read()

def clear_value():
    from prep_backend.backend import clear_value as clear
    return clear()
''',
                "test_actions.py": '''import importlib.util
import os
from pathlib import Path
from prep_backend import backend

spec = importlib.util.spec_from_file_location("prepared_test_actions", Path(os.environ["AIIFY_PREPARED_DIR"]) / "actions.py")
actions = importlib.util.module_from_spec(spec)
spec.loader.exec_module(actions)

def test_read():
    backend.STATE["value"] = 7
    assert actions.read_value() == 7

def test_clear():
    backend.STATE["value"] = 9
    assert actions.clear_value() == 0
    assert backend.STATE["value"] == 0
''',
                "guide.md": "# Values\n\n## Read a value\nUse value.read. Clearing with value.clear needs approval.\n",
                "TEST.md": "# Test plan\nVerify reads and clearing change the real backend state.\n"}}


@pytest.fixture
def bundle(backend, monkeypatch):
    root, _ = backend

    async def generate(inventory, snapshot, **kwargs):
        assert snapshot != root and (snapshot / "backend.py").is_file()
        assert inventory["source_root"] == str(root)
        return payload()

    monkeypatch.setattr(prepare, "generate", generate)
    return prepare.build(str(root), echo=lambda *args: None)


def test_build_verify_and_run_in_live_app(bundle, backend, loop_thread):
    root, module = backend
    assert prepare.check(bundle)["source_current"]
    with pytest.raises(FileNotFoundError):
        prepare.load_prepared(bundle)
    receipt = prepare.verify(bundle, echo=lambda *args: None)
    assert receipt["ok"] and receipt["counts"]["tests"] == 2
    prepared = prepare.load_prepared(bundle)
    module.STATE["value"] = 42
    agent = Agent("prepared", actions=prepared.actions, guide=prepared, limit_check_every=None)
    assert "value.clear" in agent.guide_text()
    assert loop_thread.run(agent.actions.run("value.read"))["result"] == 42
    with pytest.raises(AiifyError) as error:
        loop_thread.run(agent.actions.run("value.clear"))
    assert error.value.code == "requires_confirmation" and module.STATE["value"] == 42
    assert loop_thread.run(agent.actions.run("value.clear", confirm=True))["result"] == 0
    assert module.STATE["value"] == 0
    relocated = root.parent / "installed-bundle"
    shutil.copytree(bundle, relocated)
    assert prepare.load_prepared(relocated).actions.names() == ["value.clear", "value.read"]


def test_changed_source_and_existing_output_are_refused(bundle, backend):
    root, _ = backend
    with pytest.raises(ValueError, match="already exists"):
        prepare.build(str(root), echo=lambda *args: None)
    (root / "backend.py").write_text((root / "backend.py").read_text() + "\n# changed\n")
    with pytest.raises(ValueError, match="source is missing or changed"):
        prepare.check(bundle)


def test_edit_requires_new_verification(bundle):
    assert prepare.verify(bundle, echo=lambda *args: None)["ok"]
    guide = bundle / "guide.md"
    guide.write_text(guide.read_text() + "\nDeveloper clarification.\n")
    with pytest.raises(ValueError, match="prepared files changed"):
        prepare.load_prepared(bundle)
    assert not prepare.check(bundle)["artifacts_current"]
    assert prepare.verify(bundle, echo=lambda *args: None)["ok"]
    assert "clarification" in prepare.load_prepared(bundle).guide
    manifest = json.loads((bundle / prepare.MANIFEST).read_text())
    manifest["actions"][1]["destructive"] = False
    (bundle / prepare.MANIFEST).write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="no successful verification"):
        prepare.load_prepared(bundle)


@pytest.mark.parametrize("replacement,expected", [
    ("import pytest\npytest.skip('backend absent', allow_module_level=True)\n", "skipped"),
    ("def test_failure():\n    assert False\n", "failures"),
])
def test_skips_and_failures_never_count_as_verified(bundle, replacement, expected):
    # Keep the declared functions but skip/fail their actual execution.
    test_file = bundle / "test_actions.py"
    if expected == "skipped":
        test_file.write_text(replacement + test_file.read_text())
    else:
        test_file.write_text(test_file.read_text().replace("assert actions.read_value() == 7", "assert False"))
    receipt = prepare.verify(bundle, echo=lambda *args: None)
    assert not receipt["ok"] and receipt["counts"][expected] > 0
    with pytest.raises(ValueError, match="no successful verification"):
        prepare.load_prepared(bundle)


@pytest.mark.parametrize("change,match", [
    (lambda p: p["files"].update({"../escape.py": "pass"}), "exactly"),
    (lambda p: p["actions"][0].update(tests=[]), "test functions"),
    (lambda p: p["actions"][1].update(mutates=False), "must also be mutating"),
    (lambda p: p["actions"][0].update(function="missing"), "synchronous function"),
    (lambda p: p["actions"][0].update(destructive="false"), "booleans"),
])
def test_generated_contract_rejects_invalid_actions(change, match):
    data = payload()
    change(data)
    with pytest.raises(ValueError, match=match):
        prepare._validate(data)


def test_inventory_does_not_import_folder_and_excludes_all_prior_bundles(backend, bundle, monkeypatch):
    root, module = backend
    (root / "danger.py").write_text("raise RuntimeError('must not import')\n")
    inventory = prepare.inspect_target(str(root))
    assert any(c["name"] == "read_value" for c in inventory["candidates"])
    assert not any("aiify_prepared" in f for f in inventory["files"])
    another = root / "round-two"
    shutil.copytree(bundle, another)
    assert prepare.fingerprint(root) == inventory["source_hash"]
    with pytest.raises(ValueError, match="already exposed"):
        prepare._validate(payload(), ("value.read",))


def test_command_help_has_no_provider_import():
    result = subprocess.run([sys.executable, "-c", "import sys; from aiify import prepare; "
                             "assert 'aiify.engine' not in sys.modules; prepare.main(['--help'])"],
                            capture_output=True, text=True)
    assert result.returncode == 0 and "inspect,build,check,verify" in result.stdout


@pytest.mark.parametrize("provider", ["claude", "codex"])
def test_command_generation_through_the_actual_agent_protocol(backend, tmp_path, monkeypatch, provider):
    root, _ = backend
    reply = tmp_path / "agent-reply.json"
    reply.write_text(json.dumps(payload()), encoding="utf-8")
    monkeypatch.setenv("FAKE_ACP_PREPARED_REPLY", str(reply))
    monkeypatch.setenv("FAKE_ACP_STORE", str(tmp_path / "agent-sessions.json"))
    fake = [sys.executable, str(Path(__file__).with_name("fake_acp_agent.py"))]
    out = tmp_path / f"bundle-{provider}"
    result = subprocess.run([sys.executable, "-m", "aiify.prepare", "build", str(root),
                             "--out", str(out), "--provider", provider, "--engine", json.dumps(fake)],
                            capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr
    manifest = json.loads((out / prepare.MANIFEST).read_text())
    assert manifest["provider"] == provider
    assert not (out / prepare.RECEIPT).exists()
    assert prepare.verify(out, echo=lambda *args: None)["ok"]
    assert prepare.load_prepared(out).actions.run("value.read", {})["ok"]


def test_invalid_generation_leaves_no_bundle(backend, monkeypatch):
    root, _ = backend
    data = payload()
    data["actions"][0]["evidence"] = ["not-present.py:1"]

    async def generate(*args, **kwargs):
        return data

    monkeypatch.setattr(prepare, "generate", generate)
    with pytest.raises(ValueError, match="invalid source evidence"):
        prepare.build(str(root), echo=lambda *args: None)
    assert not (root / prepare.BUNDLE_NAME).exists()


def test_same_size_wrapper_edit_tests_new_code(bundle):
    assert prepare.verify(bundle, echo=lambda *args: None)["ok"]
    actions = bundle / "actions.py"
    before = actions.stat()
    # Same timestamp/size reproduces Python's stale bytecode-cache corner case.
    actions.write_text(actions.read_text().replace("return read()", "return 999999"))
    import os
    os.utime(actions, ns=(before.st_atime_ns, before.st_mtime_ns))
    receipt = prepare.verify(bundle, echo=lambda *args: None)
    assert not receipt["ok"] and receipt["counts"]["failures"] > 0


def test_empty_suite_never_counts_as_verified(bundle):
    tests = bundle / "test_actions.py"
    tests.write_text("__test__ = False\n" + tests.read_text())
    receipt = prepare.verify(bundle, echo=lambda *args: None)
    assert not receipt["ok"] and receipt["counts"]["tests"] == 0


def test_module_inventory_reuses_existing_actions(backend):
    from aiify.actions import from_functions
    root, module = backend
    module.agent = Agent("existing", actions=from_functions({"value.read": module.read_value}),
                         guide="The existing value reader.", limit_check_every=None)
    inventory = prepare.inspect_target("prep_backend.backend:agent")
    assert inventory["app"] == "existing"
    assert inventory["source_root"] == str(root)
    assert inventory["existing_actions"][0]["name"] == "value.read"
    assert inventory["guide"] == "The existing value reader."


def test_reply_with_narration_still_yields_the_bundle():
    # a real agent talks while it reads the source; only the last JSON object is the bundle
    data = json.dumps(payload(), indent=1)
    said = "I'll look at the backend first.Now the routes.Here is the bundle:\n"
    for reply in (said + "```json\n" + data + "\n```", said + data, data, "```json\n" + data + "\n```"):
        assert prepare._decode(reply)["actions"][0]["name"] == "value.read"
    with pytest.raises(ValueError, match="no bundle"):
        prepare._decode("I could not finish {the analysis}.")


def test_load_prepared_binds_the_host_app(backend, monkeypatch):
    # every bundle wires itself the same way, so a rebuilt bundle needs no new host code
    root, _ = backend
    data = payload()
    data["files"]["actions.py"] += "\nBOUND = []\n\ndef bind(app):\n    BOUND.append(app)\n"

    async def generate(*args, **kwargs):
        return data

    monkeypatch.setattr(prepare, "generate", generate)
    bundle = prepare.build(str(root), echo=lambda *args: None)
    assert prepare.verify(bundle, echo=lambda *args: None)["ok"]
    host = object()
    assert prepare.load_prepared(bundle, app=host).module.BOUND == [host]
    assert prepare.load_prepared(bundle).module.BOUND == []          # no app: nothing is called


def test_agent_opts_in_to_a_bundle_by_its_folder(backend, monkeypatch):
    # Agent(prepared=folder) loads the bundle once mounted, binds it to that app, and can switch it off
    from fastapi import FastAPI
    from aiify.actions import from_functions
    root, module = backend
    data = payload()
    data["files"]["actions.py"] += "\nBOUND = []\n\ndef bind(app):\n    BOUND.append(app)\n"

    async def generate(*args, **kwargs):
        return data
    monkeypatch.setattr(prepare, "generate", generate)
    bundle = prepare.build(str(root), echo=lambda *args: None)
    assert prepare.verify(bundle, echo=lambda *args: None)["ok"]
    agent = Agent("optin", actions=from_functions({"own.look": lambda: "seen"}), guide="Own guide.",
                  prepared=bundle, limit_check_every=None)
    assert agent.prepared is None and "prepared" not in agent.helpers()   # nothing until mounted
    app = FastAPI()
    agent.mount(app)
    assert agent.prepared.module.BOUND == [app]
    assert agent.helpers() == {"routes": False, "how": False, "app_map": False, "prepared": True}
    assert agent.actions.source.names() == ["own.look", "value.clear", "value.read"]
    assert "prepared actions" in agent.guide.topics() and "Own guide." in agent.guide_text()
    agent.set_helpers(prepared=False)
    assert agent.actions.source.names() == ["own.look"] and agent.guide == "Own guide."
    agent.set_helpers(prepared=True)
    assert "value.read" in agent.actions.source.names()


def test_discovery_helpers_are_off_unless_asked_for():
    agent = Agent("defaults", limit_check_every=None)
    assert agent.helpers() == {"routes": False, "how": False, "app_map": False}
