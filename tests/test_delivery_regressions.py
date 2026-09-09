"""验证安装、迁移、派发与故障边界，避免仅对实现做自证。"""
import json
from pathlib import Path

import git
import pytest

from archguard.adapters.codex.installer import install_to_project, uninstall_from_project
from archguard.adapters.codex.session_manager import CodexSessionManager, AppServerError
from archguard.adapters.git_hook import hook_path, install_post_commit_hook, uninstall_post_commit_hook
from archguard.core.engine import AuditResult
from archguard.storage import atomic_json, metadata_path
from scripts.legacy_sync_assets import migrate_assets, manifest


def test_install_preserves_custom_configuration_and_hook(tmp_path):
    repo = git.Repo.init(tmp_path)
    with repo.config_writer() as config:
        config.set_value('core', 'hooksPath', 'my-hooks')
    path = hook_path(tmp_path)
    path.parent.mkdir()
    original = b'#!/bin/sh\necho existing-hook\n'
    path.write_bytes(original)
    (tmp_path / '.codex').mkdir()
    (tmp_path / '.codex/config.toml').write_text('model = "custom"\n', encoding='utf-8')
    (tmp_path / 'AGENTS.md').write_text('# 用户规则\n', encoding='utf-8')
    install_to_project(tmp_path)
    once = path.read_bytes()
    install_to_project(tmp_path)
    assert path.read_bytes() == once
    uninstall_from_project(tmp_path)
    assert path.read_bytes() == original
    assert (tmp_path / 'AGENTS.md').read_text(encoding='utf-8').strip() == '# 用户规则'
    assert 'model = "custom"' in (tmp_path / '.codex/config.toml').read_text(encoding='utf-8')
    assert 'ide_audit_dev' not in (tmp_path / '.codex/config.toml').read_text(encoding='utf-8')


def test_changed_hook_is_not_overwritten(tmp_path):
    git.Repo.init(tmp_path)
    install_post_commit_hook(tmp_path)
    path = hook_path(tmp_path)
    path.write_text('# 用户新修改\n', encoding='utf-8')
    with pytest.raises(ValueError, match='变更'):
        uninstall_post_commit_hook(tmp_path)
    assert '用户新修改' in path.read_text(encoding='utf-8')


def test_migration_dry_run_backup_and_install(tmp_path):
    git.Repo.init(tmp_path)
    source = tmp_path / '.ai-sync/collab'
    source.mkdir(parents=True)
    (source / 'ledger.jsonl').write_text('', encoding='utf-8')
    (source / 'AUDIT_LOG.md').write_text('历史资料', encoding='utf-8')
    before = manifest(source.parent)
    assert migrate_assets(tmp_path, True)['status'] == 'planned'
    assert not (tmp_path / '.ide_audit').exists()
    result = migrate_assets(tmp_path)
    assert manifest(Path(result['backup'])) == before == manifest(source.parent)
    assert (tmp_path / '.ide_audit/collab/AUDIT_LOG.md').read_text(encoding='utf-8') == '历史资料'
    install_to_project(tmp_path)
    uninstall_from_project(tmp_path)
    with pytest.raises(ValueError, match='已有资产'):
        migrate_assets(tmp_path)


def test_migration_rolls_back_partial_publication(tmp_path, monkeypatch):
    source = tmp_path / '.ai-sync/collab'
    source.mkdir(parents=True)
    (source / 'ledger.jsonl').write_text('', encoding='utf-8')
    rename = Path.rename

    def fail_second(path, target):
        if path.name == 'codegraph' and path.parent.name == 'staged':
            raise OSError('模拟第二目录发布失败')
        return rename(path, target)

    monkeypatch.setattr(Path, 'rename', fail_second)
    with pytest.raises(OSError):
        migrate_assets(tmp_path)
    assert not (tmp_path / '.ide_audit/collab').exists()
    assert (source / 'ledger.jsonl').exists()
    records = list((tmp_path / '.ide_audit/migrations').glob('*/manifest.json'))
    assert json.loads(records[0].read_text(encoding='utf-8'))['status'] == 'rolled_back'


def make_report():
    return AuditResult(audit_id='a' * 40, commit_hash='a' * 40, timestamp='now',
                       commit_message='测试', changed_files=[{'path': 'service.py'}])


class FakeClient:
    def __init__(self, verdict):
        self.calls = []
        self.notifications = []
        self.verdict = verdict

    def __enter__(self):
        return self

    def __exit__(self, *_):
        pass

    def request(self, method, params):
        self.calls.append((method, params))
        if method.startswith('thread/'):
            return {'thread': {'id': 'real-protocol-shaped-id', 'cwd': params.get('cwd')}}
        self.notifications = [
            {'method': 'item/completed', 'params': {'threadId': 'real-protocol-shaped-id', 'turnId': 'turn1',
                'item': {'type': 'agentMessage', 'text': json.dumps(self.verdict)}}},
            {'method': 'turn/completed', 'params': {'turn': {'id': 'turn1', 'status': 'completed'}}}]
        return {'turn': {'id': 'turn1'}}


def verdict():
    return {'commit_hash': 'a' * 40, 'verdict': '合理', 'reason': '符合需求',
            'files': [{'path': 'service.py', 'related': True, 'requirement_evidence': '用户要求修改服务', 'reason': '范围匹配'}],
            'architecture_review': '没有架构变更', 'ledger_review': '申报一致'}


def test_dispatch_is_readonly_and_completed_job_is_not_sent_twice(tmp_path):
    client = FakeClient(verdict())
    manager = CodexSessionManager(tmp_path, client_factory=lambda: client)
    manager._config = lambda _: {}
    assert manager.audit(make_report()) == verdict()
    assert manager.audit(make_report()) == verdict()
    assert [method for method, _ in client.calls] == ['thread/start', 'thread/name/set', 'turn/start']
    assert client.calls[0][1]['sandbox'] == 'read-only'
    assert client.calls[2][1]['sandboxPolicy'] == {'type': 'readOnly'}
    assert all(params['approvalPolicy'] == 'never' for method, params in client.calls if method != 'thread/name/set')


@pytest.mark.parametrize('issue', ['missing_file', 'unrelated_allowed', 'wrong_commit'])
def test_invalid_verdict_is_rejected(tmp_path, issue):
    result = verdict()
    if issue == 'missing_file':
        result['files'] = []
    elif issue == 'unrelated_allowed':
        result['files'][0]['related'] = False
    else:
        result['commit_hash'] = 'b' * 40
    manager = CodexSessionManager(tmp_path, client_factory=lambda: FakeClient(result))
    manager._config = lambda _: {}
    with pytest.raises(AppServerError):
        manager.audit(make_report())
    assert not (tmp_path / '.ide_audit/verdicts').exists()


def test_uncertain_dispatch_cannot_silently_create_duplicate(tmp_path):
    atomic_json(metadata_path(tmp_path, 'jobs', 'a' * 40, 'dispatch.json'),
                {'status': 'sending', 'thread_id': 'original'})
    with pytest.raises(AppServerError, match='禁止自动重复'):
        CodexSessionManager(tmp_path).audit(make_report())


def test_recover_reads_original_turn_without_resending(tmp_path):
    class RecoveryClient(FakeClient):
        def request(self, method, params):
            self.calls.append((method, params))
            assert method == 'thread/read'
            return {'thread': {'turns': [{'id': 'original-turn', 'status': 'completed',
                'items': [{'type': 'agentMessage', 'text': json.dumps(self.verdict)}]}]}}
    client = RecoveryClient(verdict())
    atomic_json(metadata_path(tmp_path, 'jobs', 'a' * 40, 'dispatch.json'),
                {'status': 'running', 'thread_id': 'original', 'turn_id': 'original-turn'})
    manager = CodexSessionManager(tmp_path, client_factory=lambda: client)
    assert manager.recover(make_report()) == verdict()
    assert len(client.calls) == 1


def test_package_template_mirrors():
    root = Path(__file__).resolve().parents[1]
    for source in (root / 'archguard/templates').iterdir():
        assert source.read_text(encoding='utf-8') == (root / 'templates' / source.name).read_text(encoding='utf-8')
