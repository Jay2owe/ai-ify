"""Prepare app actions and guidance during development, then verify and ship them.

    python -m aiify.prepare inspect ./myapp
    python -m aiify.prepare build ./myapp --out ./prepared-round1
    python -m aiify.prepare verify ./prepared-round1

Generation follows the discover/build/test/document workflow of CLI-Anything,
adapted to ai-ify's existing action registry rather than a separate CLI runtime.
"""
from __future__ import annotations

import argparse
import ast
import asyncio
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time
from types import ModuleType, SimpleNamespace
import xml.etree.ElementTree as ET

SCHEMA_VERSION = 1
BUNDLE_NAME = "aiify_prepared"
FILES = ("actions.py", "test_actions.py", "guide.md", "TEST.md")
MANIFEST = "manifest.json"
RECEIPT = "verification.json"


def _hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _atomic_json(path: Path, value: dict) -> None:
    handle, name = tempfile.mkstemp(dir=path.parent, prefix=".aiify-", suffix=".json")
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            json.dump(value, stream, indent=2, ensure_ascii=False, allow_nan=False)
            stream.write("\n")
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def _paths(root: Path, out: Path | None = None) -> list[Path]:
    from .howto import source_files
    bundles = []
    for manifest in root.rglob(MANIFEST):
        try:
            if json.loads(manifest.read_text(encoding="utf-8")).get("kind") == "aiify.prepared":
                bundles.append(manifest.parent.resolve())
        except (OSError, ValueError, AttributeError):
            continue
    return [p for p in source_files(root) if BUNDLE_NAME not in p.relative_to(root).parts
            and (out is None or not p.resolve().is_relative_to(out.resolve()))
            and not any(p.resolve().is_relative_to(b) for b in bundles)]


def fingerprint(root: Path, out: Path | None = None) -> str:
    digest = hashlib.sha256()
    for path in _paths(root, out):
        digest.update(path.relative_to(root).as_posix().encode() + b"\0")
        digest.update(path.read_bytes().replace(b"\r\n", b"\n") + b"\0")
    return digest.hexdigest()


def inspect_target(target: str, *, source: str | None = None, out: Path | None = None) -> dict:
    """Inventory source and existing controls; never execute an app action.

    Folder targets do not import the app. Module targets import their module and
    call factories, as aiify.appmap does, to inspect live action definitions.
    """
    existing, pages, guide = [], [], ""
    path = Path(target)
    if path.is_dir():
        root = Path(source).resolve() if source else path.resolve()
        app_name = path.name
    else:
        from .appmap import gather, load_target, source_root
        app, agent, module = load_target(target)
        root = source_root(module, source)
        if app is not None and not hasattr(app, "routes"):
            app = None
        material = gather(app, agent, root)
        app_name, guide = material["app"], material["guide"]
        if agent is not None and agent.actions is not None:
            existing = agent.actions.summaries()
        elif app is not None:
            from .routes import RouteSource
            existing = RouteSource(app).describe()["actions"]
        pages = material["pages"].splitlines()
    if not root.is_dir():
        raise ValueError(f"source folder does not exist: {root}")
    files = _paths(root, out)
    candidates = []
    for file in files:
        if file.suffix != ".py":
            continue
        try:
            tree = ast.parse(file.read_text(encoding="utf-8-sig"))
        except (SyntaxError, UnicodeError):
            continue
        for node in tree.body:
            functions = [(node.name, node)] if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) else (
                [(f"{node.name}.{n.name}", n) for n in node.body
                 if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
                if isinstance(node, ast.ClassDef) else [])
            for name, fn in functions:
                if any(part.startswith("_") for part in name.split(".")):
                    continue
                candidates.append({"name": name, "source": file.relative_to(root).as_posix(),
                                   "line": fn.lineno, "summary": (ast.get_docstring(fn) or "").split("\n")[0]})
    if not files:
        raise ValueError(f"no supported source or documentation files in {root}")
    return {"schema_version": SCHEMA_VERSION, "app": app_name, "target": target,
            "source_root": str(root), "source_hash": fingerprint(root, out),
            "files": [p.relative_to(root).as_posix() for p in files],
            "existing_actions": existing, "pages": pages, "guide": guide,
            "candidates": candidates}


def _validate(payload: dict, existing: tuple[str, ...] = ()) -> dict:
    if not isinstance(payload, dict) or payload.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("prepared bundle requires schema_version 1")
    files, actions = payload.get("files"), payload.get("actions")
    if not isinstance(files, dict) or set(files) != set(FILES):
        raise ValueError(f"files must contain exactly {', '.join(FILES)}")
    if any(not isinstance(files[n], str) or not files[n].strip() for n in FILES):
        raise ValueError("every generated file must have non-empty text")
    trees = {n: ast.parse(files[n], filename=n) for n in FILES if n.endswith(".py")}
    for name in trees:
        compile(trees[name], name, "exec")
    funcs = {n.name for n in trees["actions.py"].body if isinstance(n, ast.FunctionDef)}
    tests = {n.name for n in trees["test_actions.py"].body if isinstance(n, ast.FunctionDef)
             and n.name.startswith("test_")}
    if not isinstance(actions, list):
        raise ValueError("actions must be a list")
    names = set()
    for row in actions:
        if not isinstance(row, dict):
            raise ValueError("each action must be an object")
        name = row.get("name", "")
        if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_.-]*", name):
            raise ValueError(f"invalid action name: {name!r}")
        if name in names or name in existing:
            raise ValueError(f"duplicate or already exposed action: {name}")
        names.add(name)
        if row.get("function") not in funcs:
            raise ValueError(f"action {name} must reference a synchronous function in actions.py")
        if not isinstance(row.get("summary"), str) or not row["summary"].strip():
            raise ValueError(f"action {name} needs a summary")
        if type(row.get("mutates")) is not bool or type(row.get("destructive")) is not bool:
            raise ValueError(f"action {name} needs explicit mutates and destructive booleans")
        if row["destructive"] and not row["mutates"]:
            raise ValueError(f"destructive action {name} must also be mutating")
        evidence = row.get("evidence")
        if not isinstance(evidence, list) or not evidence or any(not isinstance(e, str) or not e for e in evidence):
            raise ValueError(f"action {name} needs source evidence")
        coverage = row.get("tests")
        if not isinstance(coverage, list) or not coverage or any(not isinstance(t, str) or t not in tests for t in coverage):
            raise ValueError(f"action {name} needs existing test functions")
    if not isinstance(payload.get("analysis"), str) or not payload["analysis"].strip():
        raise ValueError("bundle needs an analysis of supported and missing controls")
    if not tests:
        raise ValueError("bundle needs real-backend tests even when no new actions are needed")
    return payload


def _decode(text: str) -> dict:
    """The bundle object from the agent's reply. The reply also holds whatever the agent
    said while it read the source, so the last JSON object (fenced or bare) is taken."""
    text = text.strip()
    for candidate in reversed([text, *re.findall(r"```(?:json)?[ \t]*\n(.*?)\n```", text, re.S)]):
        try:
            found = json.loads(candidate.strip())
        except ValueError:
            continue
        if isinstance(found, dict):
            return found
    decoder, found = json.JSONDecoder(), None
    for start in (m.start() for m in re.finditer(r"(?m)^[ \t]*\{", text)):
        try:
            obj, _ = decoder.raw_decode(text, text.index("{", start))
        except ValueError:
            continue
        if isinstance(obj, dict) and "files" in obj:
            found = obj
    if found is None:
        raise ValueError("the agent's reply holds no bundle JSON object")
    return found


async def generate(inventory: dict, root: Path, *, provider="claude", model=None, effort=None,
                   argv=None, timeout=1800.0, echo=print, keep_reply: Path | None = None) -> dict:
    from .engine import AcpSession
    chunks = []

    def event(e):
        if e.get("kind") == "text":
            chunks.append(e.get("text", ""))
        elif e.get("kind") == "tool":
            echo(f"Inspecting: {e.get('title', '')[:120]}")
        elif e.get("kind") == "status":
            echo(e.get("text", ""))
        elif e.get("kind") == "error":
            echo(f"Agent error: {e.get('text', '')}")

    async def refuse(request):
        return None

    workflow = Path(__file__).with_name("guide").joinpath("preparation-workflow.md").read_text(encoding="utf-8")
    settings = {k: v for k, v in (("model", model), ("effort", effort)) if v}
    session = AcpSession(provider, cwd=root, on_event=event, permission_handler=refuse,
                         settings=settings, argv=argv)
    deadline = asyncio.get_running_loop().time() + timeout
    try:
        await asyncio.wait_for(session.start(), min(300.0, timeout))
        remaining = max(0.0, deadline - asyncio.get_running_loop().time())
        material = {**inventory, "source_root": str(root)}
        result = await asyncio.wait_for(session.send(workflow + "\n\nInventory:\n" +
                                                     json.dumps(material, ensure_ascii=False)), remaining)
    finally:
        await session.close()
    if result.get("stop") != "end_turn":
        raise ValueError(f"generation did not finish: {result.get('stop')}; check provider sign-in")
    reply = "".join(chunks)
    try:
        return _decode(reply)
    except ValueError as exc:
        if keep_reply is None:
            raise
        keep_reply.parent.mkdir(parents=True, exist_ok=True)
        keep_reply.write_text(reply, encoding="utf-8")       # a long generation is not lost
        raise ValueError(f"{exc}; the reply is in {keep_reply}") from exc


def build(target: str, *, out=None, source=None, focus=None, provider="claude", model=None, effort=None,
          argv=None, timeout=1800.0, echo=print) -> Path:
    """Generate a separate, unverified bundle. Existing files are never replaced."""
    # Determine the output before inventorying so generation never fingerprints itself.
    inventory = inspect_target(target, source=source, out=Path(out).resolve() if out else None)
    if focus:
        inventory["focus"] = focus
    root = Path(inventory["source_root"])
    path = Path(out).resolve() if out else root / BUNDLE_NAME
    if path.exists():
        raise ValueError(f"output already exists: {path}; choose a new --out folder for another round")
    echo(f"Inspecting {len(inventory['files'])} source files; {len(inventory['existing_actions'])} actions already exposed.")
    started = time.monotonic()
    paths = _paths(root, path)
    snapshot_bytes = sum(p.stat().st_size for p in paths)
    if snapshot_bytes > 32 * 1024 * 1024:
        raise ValueError("source snapshot exceeds 32 MB; use --source to select the app's backend and docs")
    if shutil.disk_usage(tempfile.gettempdir()).free < 2 * snapshot_bytes + 16 * 1024 * 1024:
        raise ValueError("insufficient temporary disk space for source snapshot and generated output")
    # Source copies keep generation work away from the developer's checkout.
    with tempfile.TemporaryDirectory(prefix="aiify-prepare-") as temporary:
        snapshot = Path(temporary)
        for file in paths:
            copied = snapshot / file.relative_to(root)
            copied.parent.mkdir(parents=True, exist_ok=True)
            copied.write_bytes(file.read_bytes())
        payload = asyncio.run(generate(inventory, snapshot, provider=provider, model=model, effort=effort,
                                       argv=argv, timeout=timeout, echo=echo,
                                       keep_reply=path.with_name(path.name + "-reply.txt")))
    _validate(payload, tuple(r["name"] for r in inventory["existing_actions"]))
    for action in payload["actions"]:
        for evidence in action["evidence"]:
            file, separator, line = evidence.rpartition(":")
            if not separator or file not in inventory["files"] or not line.isdigit() \
                    or not 1 <= int(line) <= len((root / file).read_text(encoding="utf-8-sig").splitlines()):
                raise ValueError(f"action {action['name']} has invalid source evidence: {evidence}")
    if fingerprint(root, path) != inventory["source_hash"]:
        raise ValueError("source changed during generation; rebuild against a stable checkout")
    path.mkdir(parents=True)
    for name in FILES:
        (path / name).write_text(payload["files"][name].rstrip() + "\n", encoding="utf-8")
    from . import __version__
    manifest = {"schema_version": SCHEMA_VERSION, "kind": "aiify.prepared", "aiify_version": __version__,
                "app": inventory["app"], "target": target,
                "source_root": str(root), "source_hash": inventory["source_hash"],
                "analysis": payload["analysis"], "actions": payload["actions"],
                "provider": provider, "model": model, "effort": effort,
                "built": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "artifacts": {n: _hash((path / n).read_bytes()) for n in FILES}}
    _atomic_json(path / MANIFEST, manifest)
    echo(f"Wrote {path} in {time.monotonic() - started:.1f} s. Review it, then run aiify.prepare verify.")
    return path


def _read_bundle(path: Path, *, require_hashes=True) -> tuple[dict, dict]:
    manifest = json.loads((path / MANIFEST).read_text(encoding="utf-8"))
    if manifest.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("unsupported prepared bundle schema")
    files = {n: (path / n).read_text(encoding="utf-8") for n in FILES}
    _validate({**manifest, "files": files})
    artifacts = {n: _hash((path / n).read_bytes()) for n in FILES}
    if require_hashes and artifacts != manifest.get("artifacts"):
        raise ValueError("prepared files changed; run aiify.prepare verify before loading")
    return manifest, artifacts


def check(path: str | Path, *, source=None) -> dict:
    """Check syntax, action/test coverage and source freshness without loading wrappers."""
    path = Path(path).resolve()
    manifest, artifacts = _read_bundle(path, require_hashes=False)
    root = Path(source or manifest["source_root"]).resolve()
    if not root.is_dir() or fingerprint(root, path) != manifest["source_hash"]:
        raise ValueError("source is missing or changed; pass --source for a relocated checkout or rebuild")
    return {"ok": True, "actions": len(manifest["actions"]), "source_current": True,
            "artifacts_current": artifacts == manifest.get("artifacts"), "artifacts": artifacts}


def verify(path: str | Path, *, source=None, timeout=300.0, echo=print) -> dict:
    """Run generated pytest tests against disposable app data; reject skips and empty suites."""
    path = Path(path).resolve()
    check(path, source=source)
    manifest, artifacts = _read_bundle(path, require_hashes=False)
    if artifacts != manifest.get("artifacts"):
        manifest["artifacts"] = artifacts
        _atomic_json(path / MANIFEST, manifest)
    manifest_hash = _hash((path / MANIFEST).read_bytes())
    root = Path(source or manifest["source_root"]).resolve()
    echo("Running generated tests against the app backend ...")
    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="aiify-verify-") as temporary:
        report = Path(temporary) / "tests.xml"
        env = os.environ.copy()
        # Support both a source checkout and its src/ layout without a shell command.
        env["PYTHONPATH"] = os.pathsep.join([str(root), str(root / "src"), str(root.parent),
                                             str(Path(__file__).resolve().parents[1]),
                                             env.get("PYTHONPATH", "")])
        env["AIIFY_PREPARED_DIR"] = str(path)
        env["AIIFY_VERIFY_DIR"] = temporary
        env["AIIFY_HOME"] = str(Path(temporary) / "aiify-home")
        env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
        # Fresh caches ensure edited wrappers/backend files are the ones tested.
        env["PYTHONPYCACHEPREFIX"] = str(Path(temporary) / "pycache")
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        command = [sys.executable, "-m", "pytest", str(path / "test_actions.py"),
                   "-q", "--confcutdir", str(path), "--junitxml", str(report),
                   "-o", "addopts=", "-o", "junit_family=xunit2"]
        try:
            result = subprocess.run(command, cwd=root, env=env, capture_output=True, text=True,
                                    encoding="utf-8", errors="replace", timeout=timeout)
            output, returncode = result.stdout + result.stderr, result.returncode
        except subprocess.TimeoutExpired:
            output, returncode = f"Generated tests exceeded {timeout:g} seconds.", -1
        counts = {"tests": 0, "failures": 0, "errors": 0, "skipped": 0}
        names = set()
        if report.is_file():
            suites = ET.parse(report).getroot()
            for case in suites.iter("testcase"):
                counts["tests"] += 1
                names.add(case.get("name", "").split("[", 1)[0])
                for kind in ("failure", "error", "skipped"):
                    if case.find(kind) is not None:
                        counts[{"failure": "failures", "error": "errors", "skipped": "skipped"}[kind]] += 1
        covered = all(set(a["tests"]) <= names for a in manifest["actions"])
        unchanged = (artifacts == {n: _hash((path / n).read_bytes()) for n in FILES}
                     and manifest_hash == _hash((path / MANIFEST).read_bytes()))
        source_current = root.is_dir() and fingerprint(root, path) == manifest["source_hash"]
        ok = (returncode == 0 and counts["tests"] > 0 and not any(counts[k] for k in
              ("failures", "errors", "skipped")) and covered and unchanged and source_current)
    receipt = {"schema_version": SCHEMA_VERSION, "ok": ok, "counts": counts,
               "all_actions_covered": covered, "artifacts_unchanged": unchanged,
               "source_current": source_current, "artifacts": artifacts,
               "manifest_hash": manifest_hash, "command": command,
               "python": sys.version, "returncode": returncode,
               "elapsed_s": round(time.monotonic() - started, 3),
               "verified": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "output": output}
    _atomic_json(path / RECEIPT, receipt)
    echo(output.strip())
    echo("Verified." if ok else "Verification failed; see verification.json.")
    return receipt


@dataclass
class Prepared:
    """Shipped actions and their guide. Importing the wrappers executes Python code."""
    actions: object
    guide: str
    manifest: dict
    module: object = None              # the loaded actions.py, for wiring such as a bind() it defines

    def read(self, topic=None) -> str:
        return self.guide


def load_prepared(path: str | Path, app: object = None) -> Prepared:
    """Load developer-reviewed, verified wrappers into the existing action registry.
    With ``app``, the bundle's ``bind(app)`` (if it defines one) is called once, so
    wrappers reach the host's live state without bundle-specific wiring."""
    from .actions import from_registry
    path = Path(path).resolve()
    manifest, artifacts = _read_bundle(path)
    receipt = json.loads((path / RECEIPT).read_text(encoding="utf-8"))
    if receipt.get("schema_version") != SCHEMA_VERSION or receipt.get("ok") is not True \
            or receipt.get("artifacts") != artifacts \
            or receipt.get("manifest_hash") != _hash((path / MANIFEST).read_bytes()):
        raise ValueError("bundle has no successful verification for these files; run aiify.prepare verify")
    name = "_aiify_prepared_" + _hash(str(path).encode())[:16]
    # Compile from the verified bytes, avoiding stale .pyc caches after another round.
    module = ModuleType(name)
    module.__file__ = str(path / "actions.py")
    sys.modules[name] = module
    try:
        exec(compile((path / "actions.py").read_bytes(), module.__file__, "exec"), module.__dict__)
    except BaseException:
        sys.modules.pop(name, None)
        raise
    mapping = {}
    for row in manifest["actions"]:
        fn = getattr(module, row["function"], None)
        if not callable(fn):
            raise ValueError(f"prepared function is not callable: {row['function']}")
        mapping[row["name"]] = SimpleNamespace(fn=fn, summary=row["summary"],
                                               mutates=row["mutates"], destructive=row["destructive"])
    if app is not None and callable(getattr(module, "bind", None)):
        module.bind(app)
    return Prepared(from_registry(mapping), (path / "guide.md").read_text(encoding="utf-8"), manifest, module)


def main(args=None) -> int:
    parser = argparse.ArgumentParser(prog="python -m aiify.prepare", description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    for cmd in ("inspect", "build"):
        p = sub.add_parser(cmd)
        p.add_argument("target", help="source folder or module:attribute of the app/Agent/factory")
        p.add_argument("--source", help="source folder for a module target")
        if cmd == "build":
            p.add_argument("--out", help=f"new output folder (default: {BUNDLE_NAME} in the source)")
            p.add_argument("--provider", choices=("claude", "codex"), default="claude")
            p.add_argument("--model")
            p.add_argument("--effort")
            p.add_argument("--focus", help="tasks or operations the assistant should support")
            p.add_argument("--timeout", type=float, default=1800)
            p.add_argument("--engine", help=argparse.SUPPRESS)
    for cmd in ("check", "verify"):
        p = sub.add_parser(cmd)
        p.add_argument("path", help="prepared bundle folder")
        p.add_argument("--source", help="source folder if the checkout moved")
        if cmd == "verify":
            p.add_argument("--timeout", type=float, default=300)
    a = parser.parse_args(args)
    progress = lambda message: print(message, flush=True)
    try:
        if a.command == "inspect":
            print(json.dumps(inspect_target(a.target, source=a.source), indent=2, ensure_ascii=True))
        elif a.command == "build":
            build(a.target, source=a.source, out=a.out, focus=a.focus, provider=a.provider, model=a.model,
                  effort=a.effort, timeout=a.timeout, argv=json.loads(a.engine) if a.engine else None,
                  echo=progress)
        elif a.command == "check":
            print(json.dumps(check(a.path, source=a.source)))
        elif a.command == "verify":
            return 0 if verify(a.path, source=a.source, timeout=a.timeout, echo=progress)["ok"] else 1
    except (ValueError, OSError, SyntaxError, ImportError, asyncio.TimeoutError) as exc:
        print(f"Preparation failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
