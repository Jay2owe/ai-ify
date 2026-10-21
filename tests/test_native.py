"""Native runner controls must never change the host's global account or spend tokens."""
import json
from pathlib import Path
import pytest
from aiify.native import codex_command,codex_environment,validate_account


def test_exact_model_effort_and_permissions(monkeypatch):
    monkeypatch.setattr('aiify.native.shutil.which',lambda name:'codex.exe')
    cmd=codex_command('exact-sol','high','out.txt')
    assert cmd[cmd.index('-m')+1]=='exact-sol'
    assert 'model_reasoning_effort="high"' in cmd
    assert cmd[cmd.index('-s')+1]=='workspace-write'
    assert '--dangerously-bypass-approvals-and-sandbox' not in cmd


def test_account_isolation_retains_refreshed_auth_and_never_loads_global(tmp_path,monkeypatch):
    original=tmp_path/'original';original.mkdir();(original/'config.toml').write_text('model="exact"')
    (original/'auth.json').write_text('unchanged-global')
    monkeypatch.setenv('CODEX_HOME',str(original));monkeypatch.setenv('CODEX_THREAD_ID','parent-session')
    monkeypatch.setenv('OPENAI_API_KEY','fixture-only');monkeypatch.setenv('CODEX_API_KEY','fixture-only')
    calls=[]
    def profile(*args):
        calls.append(args)
        if args[0]=='list':return {'profiles':[{'id':'account-a','is_saved':True,'is_current':True}]}
        assert args[0]=='export'
        Path(args[-1]).write_text(json.dumps({'profiles':[{'id':'account-a','contents':{'tokens':{'fake':'fixture-only'}}}]}))
        return {'success':True}
    env=codex_environment('account-a',root=tmp_path/'private',run=profile)
    assert 'CODEX_THREAD_ID' not in env
    assert 'OPENAI_API_KEY' not in env and 'CODEX_API_KEY' not in env
    target=Path(env['CODEX_HOME']);assert target!=original
    assert (target/'config.toml').read_text()=='model="exact"'
    (target/'auth.json').write_text('refreshed-credentials')
    assert codex_environment('account-a',root=tmp_path/'private',run=profile)==env
    assert (target/'auth.json').read_text()=='refreshed-credentials'
    assert (original/'auth.json').read_text()=='unchanged-global'
    assert len([c for c in calls if c[0]=='export'])==1
    assert not list(target.glob('profile-*'))


def test_missing_account_and_api_key_refuse_instead_of_substitution(tmp_path):
    for row in ([],[{'id':'a','is_saved':True,'is_api_key':True}]):
        with pytest.raises(Exception):codex_environment('a',root=tmp_path,run=lambda *a:{'profiles':row})
    with pytest.raises(ValueError):validate_account('../other')


@pytest.mark.parametrize('failure',[False,True])
def test_command_probe_uses_no_model_turn_and_cleans_process(tmp_path,failure):
    import sys
    from aiify.native import probe_codex_shell
    script=tmp_path/'server.py';log=tmp_path/'requests.jsonl'
    script.write_text('''import sys,json
from pathlib import Path
for line in sys.stdin:
    value=json.loads(line)
    with Path(sys.argv[1]).open('a') as stream:stream.write(json.dumps(value)+'\\n')
    if 'id' not in value:continue
    result={} if value['method']=='initialize' else {'exitCode':int(sys.argv[2]),'stdout':'aiify-shell-ready','stderr':'fixture failure'}
    print(json.dumps({'id':value['id'],'result':result}),flush=True)
''')
    argv=[sys.executable,str(script),str(log),str(int(failure))]
    if failure:
        with pytest.raises(RuntimeError,match='fixture failure'):probe_codex_shell(tmp_path,argv=argv,timeout=10)
    else:assert probe_codex_shell(tmp_path,argv=argv,timeout=10)['ready']
    requests=[json.loads(line) for line in log.read_text().splitlines()]
    assert [r['method'] for r in requests]==['initialize','initialized','command/exec']
    assert requests[-1]['params']['sandboxPolicy']['type']=='workspaceWrite'


def test_native_write_roots_are_explicit_and_deduplicated(tmp_path,monkeypatch):
    monkeypatch.setattr('aiify.native.shutil.which',lambda name:'codex.exe')
    cmd=codex_command('exact','high',writable_roots=[tmp_path,tmp_path])
    assert cmd.count('--add-dir')==1
    assert cmd[cmd.index('--add-dir')+1]==str(tmp_path.resolve())
