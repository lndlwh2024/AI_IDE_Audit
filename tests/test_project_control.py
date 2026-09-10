import json
import shutil
import git
import pytest
from archguard import project_control as control
from archguard import dispatch_queue, usage
from archguard.storage import metadata_path, read_json
from archguard.sync.prompts import record_prompt


@pytest.fixture(autouse=True)
def local_catalog(monkeypatch):
    monkeypatch.setattr(control, 'verify_project', lambda root: None)


def test_unselected_never_creates_metadata_or_worker(tmp_path, monkeypatch):
    assert control.status(tmp_path)['status'] == 'unselected'
    monkeypatch.setattr(dispatch_queue.subprocess, 'Popen', lambda *a, **k: pytest.fail('启动了后台'))
    dispatch_queue.start_worker(tmp_path)
    dispatch_queue.drain(tmp_path)
    with pytest.raises(PermissionError):
        dispatch_queue.enqueue(tmp_path, 'a' * 40)
    with pytest.raises(PermissionError):
        control.choose(tmp_path, 'p', True)
    assert not (tmp_path / '.ide_audit').exists()


def test_authorization_is_project_local_and_copy_does_not_inherit(tmp_path):
    a, b = tmp_path / 'a', tmp_path / 'b'
    a.mkdir(); b.mkdir()
    control.choose(a, 'project-a', True, confirmed=True)
    assert control.status(b)['status'] == 'unselected'
    shutil.copytree(a / '.ide_audit', b / '.ide_audit')
    assert control.status(b)['status'] == 'unselected'
    (b / '.ide_audit/project-control.json').write_text('{', encoding='utf-8')
    assert control.status(b)['status'] == 'unselected'


def test_resume_waits_for_a_and_archives_old_prompt(tmp_path):
    git.Repo.init(tmp_path)
    (tmp_path / 'a.py').write_text('value=1', encoding='utf-8')
    control.choose(tmp_path, 'p', True, confirmed=True)
    assert control.status(tmp_path)['status'] == 'pending_a'
    result = control.refresh_a(tmp_path, 'codex')
    assert control.status(tmp_path)['status'] == 'enabled'
    record_prompt(tmp_path, '旧需求')
    before = metadata_path(tmp_path, 'codegraph', 'graph.json').read_bytes()
    control.pause(tmp_path)
    (tmp_path / 'a.py').write_text('value=2', encoding='utf-8')
    control.resume(tmp_path)
    assert metadata_path(tmp_path, 'codegraph', 'graph.json').read_bytes() == before
    with pytest.raises(PermissionError): control.require(tmp_path)
    control.refresh_a(tmp_path, 'codex', result['session_id'])
    assert read_json(metadata_path(tmp_path, 'prompts', 'pending.json')) == []
    assert list(metadata_path(tmp_path, 'prompts', 'archived').glob('resume-*.json'))


def test_failed_a_refresh_keeps_project_blocked(tmp_path):
    git.Repo.init(tmp_path)
    control.choose(tmp_path, 'p', True, confirmed=True)
    control.refresh_a(tmp_path, 'codex')
    (tmp_path / 'bad.py').write_text('def broken(', encoding='utf-8')
    with pytest.raises(ValueError): control.refresh_a(tmp_path, 'codex')
    assert control.status(tmp_path)['status'] == 'pending_a'


def test_usage_snapshots_are_not_summed_twice_and_missing_is_unknown(tmp_path):
    before = {'counts': {'totalTokens': 100}}
    after = {'counts': {'totalTokens': 150}, 'status': 'observed'}
    usage.save(tmp_path, 'b', 't', 'audit', before, after)
    usage.save(tmp_path, 'b', 't', 'audit', before, after)
    report = usage.report(tmp_path)
    assert report['observed_total_tokens'] == 150
    assert report['threads'][0]['turns']['t']['counts']['totalTokens'] == 50
    reset = usage.save(tmp_path, 'b', 't2', 'audit2', after, {'counts': {'totalTokens': 2}})
    assert reset['counts']['totalTokens'] is None
    class Client:
        def request(self, *args): raise RuntimeError('不可用')
    assert usage.capture(tmp_path, Client(), 'b')['counts']['totalTokens'] is None
