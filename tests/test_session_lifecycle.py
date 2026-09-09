"""同项目 B、重启复用和会话缺失后的策略。"""
from pathlib import Path
import pytest
from archguard.adapters.codex.session_manager import CodexSessionManager, AppServerError
from archguard.storage import atomic_json, read_json


class Client:
    def __init__(self, root, error=None, returned_root=None):
        self.root = root
        self.error = error
        self.returned_root = returned_root or root
        self.calls = []

    def request(self, method, params):
        self.calls.append((method, params))
        if method == 'thread/resume' and self.error:
            raise self.error
        return {'thread': {'id': params.get('threadId', 'new-b'), 'cwd': str(self.returned_root)}}


def test_restart_keeps_project_and_same_thread(tmp_path):
    atomic_json(tmp_path / '.ide_audit/session.json', {'project_root': str(tmp_path), 'thread_id': 'old-b'})
    client = Client(tmp_path)
    manager = CodexSessionManager(tmp_path)
    assert manager._open_session(client, {'cwd': str(tmp_path)}) == 'old-b'
    assert [method for method, _ in client.calls] == ['thread/resume']
    assert client.calls[0][1]['cwd'] == str(tmp_path)


def test_missing_thread_creates_fresh_b_without_replaying_history(tmp_path):
    atomic_json(tmp_path / '.ide_audit/session.json', {'project_root': str(tmp_path), 'thread_id': 'old-b'})
    error = AppServerError('会话不存在', {'code': -32600, 'message': 'no rollout found for thread id old-b'})
    client = Client(tmp_path, error)
    manager = CodexSessionManager(tmp_path)
    assert manager._open_session(client, {'cwd': str(tmp_path)}) == 'new-b'
    assert [method for method, _ in client.calls] == ['thread/resume', 'thread/start']
    assert all('history' not in params and 'input' not in params for _, params in client.calls)
    state = read_json(manager.session_file)
    assert state['history_policy'] == 'fresh_after_missing'
    assert state['previous_thread_id'] == 'old-b'


@pytest.mark.parametrize('message', ['thread not loaded: old-b', 'authentication failed', 'connection closed'])
def test_transient_or_auth_failure_must_not_recreate(tmp_path, message):
    original = {'project_root': str(tmp_path), 'thread_id': 'old-b'}
    atomic_json(tmp_path / '.ide_audit/session.json', original)
    client = Client(tmp_path, AppServerError(message, {'code': -32600, 'message': message}))
    manager = CodexSessionManager(tmp_path)
    with pytest.raises(AppServerError):
        manager._open_session(client, {'cwd': str(tmp_path)})
    assert len(client.calls) == 1
    assert read_json(manager.session_file) == original


def test_server_wrong_project_is_rejected(tmp_path):
    client = Client(tmp_path, returned_root=tmp_path / 'other-project')
    manager = CodexSessionManager(tmp_path)
    with pytest.raises(AppServerError, match='与 A 项目不一致'):
        manager._open_session(client, {'cwd': str(tmp_path)})
    assert not manager.session_file.exists()


def test_local_project_binding_cannot_be_overridden(tmp_path):
    atomic_json(tmp_path / '.ide_audit/session.json', {'project_root': str(tmp_path / 'other'), 'thread_id': 'old-b'})
    client = Client(tmp_path)
    with pytest.raises(AppServerError, match='归属项目不匹配'):
        CodexSessionManager(tmp_path)._open_session(client, {'cwd': str(tmp_path)})
    assert not client.calls


def test_session_without_project_must_not_use_current_directory(tmp_path):
    atomic_json(tmp_path / '.ide_audit/session.json', {'thread_id': 'old-b'})
    client = Client(tmp_path)
    with pytest.raises(AppServerError, match='归属项目不匹配'):
        CodexSessionManager(tmp_path)._open_session(client, {'cwd': str(tmp_path)})
    assert not client.calls


def test_archived_b_is_replaced_without_unarchiving_or_replaying(tmp_path):
    atomic_json(tmp_path / '.ide_audit/session.json', {'project_root': str(tmp_path), 'thread_id': 'old-b'})
    message = 'session old-b is archived. Run `codex unarchive old-b` to unarchive it first.'
    client = Client(tmp_path, AppServerError(message, {'code': -32600, 'message': message}))
    manager = CodexSessionManager(tmp_path)
    assert manager._open_session(client, {'cwd': str(tmp_path)}) == 'new-b'
    assert [method for method, _ in client.calls] == ['thread/resume', 'thread/start']
    assert read_json(manager.session_file)['history_policy'] == 'fresh_after_archived'
    history = list((tmp_path / '.ide_audit/session-history').glob('*.json'))
    assert read_json(history[0])['state'] == 'archived'
    assert all('history' not in params and params['cwd'] == str(tmp_path) for _, params in client.calls)
