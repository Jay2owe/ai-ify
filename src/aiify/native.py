"""Shared settings and isolated account environments for host-owned native runners.

No model is called. The host keeps its durable queue and native image tools.
Credentials live in the user's ai-ify home, never in a host's project or receipts.
"""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

from .accounts import CodexAccounts, ProfileError, run_profile
from .engine import child_env
from .protocol import home


def account_choices(provider='codex'):
    if provider!='codex':
        return {'current':None,'choices':[],'error':None,'label':'Current Claude login'}
    return CodexAccounts().refresh()


def validate_account(value):
    if not isinstance(value,str) or (value and not re.fullmatch(r'[\w@.+-]{1,160}',value,re.ASCII)):
        raise ValueError('Choose a saved account or the current login.')
    return value


def codex_environment(account='',*,root=None,run=run_profile):
    """Use one persistent auth home per saved account, without switching global login.

    Already refreshed credentials are retained. Shared native configuration and
    skills remain reachable; the caller must report setup failures, never run as
    another account. Test callers supply both root and a fake profile command.
    """
    account=validate_account(account)
    env=child_env()
    for key in ('CODEX_THREAD_ID','CODEX_SESSION_ID'):
        env.pop(key,None)
    if not account:return env
    # An explicitly selected subscription must not inherit a competing API key.
    env.pop('OPENAI_API_KEY',None)
    env.pop('CODEX_API_KEY',None)
    profiles=run('list').get('profiles') or []
    selected=next((r for r in profiles if r.get('id')==account and r.get('is_saved')),None)
    if not selected:raise ProfileError('The selected saved Codex account is unavailable.')
    if selected.get('is_api_key'):raise ProfileError('Choose a subscription account for this runner.')
    original=Path(os.environ.get('CODEX_HOME') or Path.home()/'.codex').resolve()
    base=Path(root) if root is not None else home()/'native-accounts'
    target=base/hashlib.sha256(account.encode()).hexdigest()[:24]
    target.mkdir(parents=True,exist_ok=True)
    auth=target/'auth.json'
    if not auth.exists():
        with tempfile.TemporaryDirectory(prefix='profile-',dir=target) as temporary:
            export=Path(temporary)/'profile.json'
            run('export','--id',account,'--output',str(export))
            rows=json.loads(export.read_text(encoding='utf-8')).get('profiles') or []
            row=next((r for r in rows if r.get('id')==account),None)
            if not row or not isinstance(row.get('contents'),dict):raise ProfileError('Saved account export was incomplete.')
            if row['contents'].get('OPENAI_API_KEY'):raise ProfileError('A subscription account is required.')
            # Exclusive creation prevents a simultaneous launch overwriting newer auth.
            prepared=Path(temporary)/'auth.json'
            prepared.write_text(json.dumps(row['contents']),encoding='utf-8');prepared.chmod(0o600)
            try:os.link(prepared,auth)
            except FileExistsError:pass
    # Keep native capabilities/configuration; account state alone is independent.
    # Junctions avoid duplicating a potentially large installed plugin collection.
    for name in ('skills','plugins','rules'):
        source=original/name;link=target/name
        if source.is_dir() and not link.exists():
            if os.name=='nt':
                result=subprocess.run(['cmd.exe','/d','/c','mklink','/J',str(link),str(source)],
                    capture_output=True,creationflags=subprocess.CREATE_NO_WINDOW)
                if result.returncode and not link.exists():raise ProfileError('Could not attach native agent resources.')
            else:
                try:link.symlink_to(source,target_is_directory=True)
                except FileExistsError:pass
    for name in ('config.toml','hooks.json','AGENTS.md'):
        source=original/name
        if source.is_file():
            raw=source.read_bytes();destination=target/name
            if not destination.exists() or destination.read_bytes()!=raw:
                with tempfile.NamedTemporaryFile(dir=target,delete=False) as stream:
                    stream.write(raw);temporary=Path(stream.name)
                os.replace(temporary,destination)
    env['CODEX_HOME']=str(target)
    return env


MODEL=re.compile(r'[A-Za-z0-9][A-Za-z0-9._:-]{0,59}')
EFFORT=re.compile(r'[A-Za-z0-9][A-Za-z0-9_-]{0,19}')
# cmd.exe expands %/! and splits on &|<>^ even inside quotes; a .cmd launcher re-parses every argument.
_CMD_UNSAFE=re.compile(r'[&|<>^%!\r\n\x00]')
_CMD_QUOTED=re.compile(r'[\w.]+="[\w-]*"')  # key="value" overrides keep balanced quotes


def validate_model(value):
    """An exact model name; a leading letter or digit stops it being read as a flag."""
    if not isinstance(value,str) or (value and not MODEL.fullmatch(value)):
        raise ValueError('Give an exact Codex model name (letters, digits, . _ : -), or leave it empty for the default.')
    return value


def validate_effort(value):
    if not isinstance(value,str) or (value and not EFFORT.fullmatch(value)):raise ValueError('Unknown Codex reasoning effort.')
    return value


def _launcher():
    """Codex's program, run without the npm .cmd shim where possible so cmd.exe never parses arguments."""
    exe=shutil.which('codex') or shutil.which('codex.cmd')
    if not exe:raise FileNotFoundError('Codex is not installed or is missing from PATH.')
    if Path(exe).suffix.lower() not in ('.cmd','.bat'):return [exe]
    folder=Path(exe).parent;script=folder/'node_modules/@openai/codex/bin/codex.js'
    node=str(folder/'node.exe') if (folder/'node.exe').is_file() else shutil.which('node')
    return [node,str(script)] if node and script.is_file() else [exe]


def _cmd_safe(argv):
    if Path(argv[0]).suffix.lower() in ('.cmd','.bat'):
        for part in argv[1:]:
            if _CMD_UNSAFE.search(part) or ('"' in part and not _CMD_QUOTED.fullmatch(part)):
                raise ValueError('Refusing an argument cmd.exe would reinterpret: '+part[:80])
    return argv


def codex_command(model='',effort='',output='last-message.txt',*,writable_roots=()):
    """Native image-capable Codex, with exact settings and bounded permissions."""
    model=validate_model(model);effort=validate_effort(effort)
    argv=[*_launcher(),'exec','--skip-git-repo-check','-s','workspace-write','-o',str(output)]
    if os.name=='nt':argv+=['-c','windows.sandbox="unelevated"']
    for root in dict.fromkeys(str(Path(p).resolve()) for p in writable_roots):argv+=['--add-dir',root]
    if model:argv+=['-m',model]
    if effort:argv+=['-c','model_reasoning_effort='+json.dumps(effort)]
    return _cmd_safe(argv+['-'])


def probe_codex_shell(cwd,*,env=None,timeout=20,argv=None):
    """Run a fixed harmless shell check through Codex, without a model turn.

    This uses the installed app-server protocol's command/exec. Never weakens
    sandbox permissions or retries using another account/provider.
    """
    import queue
    import threading
    import time
    from .engine import kill_tree
    command=argv or [*_launcher(),*(['-c','windows.sandbox="unelevated"'] if os.name=='nt' else []),'app-server','--stdio']
    responses=queue.Queue();started=time.monotonic()
    with tempfile.TemporaryFile(mode='w+b') as errors:
        process=subprocess.Popen(command,cwd=cwd,env=env or child_env(),stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,stderr=errors,text=True,encoding='utf-8',errors='replace',
            creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        def read():
            for line in process.stdout:
                try:responses.put(json.loads(line))
                except ValueError:continue
            responses.put({'closed':True})
        reader=threading.Thread(target=read,daemon=True);reader.start()
        def send(value):process.stdin.write(json.dumps(value)+'\n');process.stdin.flush()
        def receive(identity):
            while True:
                remaining=timeout-(time.monotonic()-started)
                if remaining<=0:raise TimeoutError('Codex command runner did not respond within the startup limit.')
                try:value=responses.get(timeout=remaining)
                except queue.Empty:raise TimeoutError('Codex command runner did not respond within the startup limit.') from None
                if value.get('closed'):raise RuntimeError('Codex command runner exited during startup.')
                if value.get('id')==identity:
                    if 'error' in value:raise RuntimeError('Codex command runner: '+str(value['error'].get('message','request failed'))[:600])
                    return value.get('result') or {}
        try:
            send({'id':1,'method':'initialize','params':{'clientInfo':{'name':'aiify-runner-check','version':'1'},'capabilities':{'experimentalApi':True}}})
            receive(1);send({'method':'initialized','params':{}})
            shell=['powershell.exe','-NoProfile','-NonInteractive','-Command','Write-Output aiify-shell-ready'] if os.name=='nt' else ['/bin/sh','-c','printf aiify-shell-ready']
            send({'id':2,'method':'command/exec','params':{'command':shell,'cwd':str(Path(cwd).resolve()),
                'timeoutMs':10000,'sandboxPolicy':{'type':'workspaceWrite','writableRoots':[str(Path(cwd).resolve())],'networkAccess':True}}})
            result=receive(2)
            if result.get('exitCode')!=0 or 'aiify-shell-ready' not in result.get('stdout',''):
                raise RuntimeError('Codex shell startup failed: '+str(result.get('stderr') or 'no successful command response')[:600])
            return {'ready':True,'seconds':time.monotonic()-started}
        finally:
            if process.poll() is None:kill_tree(process.pid)
            try:process.wait(timeout=5)
            except subprocess.TimeoutExpired:process.kill()
            process.stdin.close();reader.join(timeout=1);process.stdout.close()
