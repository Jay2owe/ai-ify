"""On Windows `codex` is an npm .cmd shim, so cmd.exe would re-parse every argument."""
import pytest
from aiify.native import codex_command


@pytest.mark.parametrize('model',['a&b','x&calc','"a','-c','a b','a|b','%PATH%','a^b','é'])
def test_unsafe_model_is_refused_before_launch(monkeypatch,model):
    monkeypatch.setattr('aiify.native.shutil.which',lambda name:'codex.exe')
    with pytest.raises(ValueError):codex_command(model)


@pytest.mark.parametrize('effort',['high"&calc','-x','a b'])
def test_unsafe_effort_is_refused(monkeypatch,effort):
    monkeypatch.setattr('aiify.native.shutil.which',lambda name:'codex.exe')
    with pytest.raises(ValueError):codex_command('gpt-5.1-codex',effort)


def test_cmd_shim_is_bypassed_for_node_and_script(tmp_path,monkeypatch):
    shim=tmp_path/'codex.cmd';shim.write_text('@echo off')
    script=tmp_path/'node_modules/@openai/codex/bin/codex.js';script.parent.mkdir(parents=True);script.write_text('')
    (tmp_path/'node.exe').write_text('')
    monkeypatch.setattr('aiify.native.shutil.which',lambda name:str(shim) if name.startswith('codex') else None)
    cmd=codex_command('gpt-5:mini','high')
    assert cmd[:2]==[str(tmp_path/'node.exe'),str(script)] and cmd[2]=='exec'
    assert cmd[cmd.index('-m')+1]=='gpt-5:mini'


def test_unresolvable_shim_refuses_cmd_metacharacters(tmp_path,monkeypatch):
    shim=tmp_path/'codex.cmd';shim.write_text('@echo off')
    monkeypatch.setattr('aiify.native.shutil.which',lambda name:str(shim) if name.startswith('codex') else None)
    assert codex_command('exact','high')[0]==str(shim)  # balanced fixed overrides still pass
    with pytest.raises(ValueError,match='reinterpret'):codex_command('exact',writable_roots=[tmp_path/'R&D'])
