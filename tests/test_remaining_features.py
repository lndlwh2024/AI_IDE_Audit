"""增量依赖重解析、目录租约和跨步骤恢复验收。"""
import ast
import pytest
from archguard.core.codegraph import build_graph
from archguard.sync.graph import GraphManager
from archguard.sync.lock import SyncLock, LockError
from archguard.sync.workflow import SyncWorkflow
from archguard.sync.ledger import LedgerManager
from archguard.storage import read_json
from tests.test_audit_regressions import event


def test_incremental_matches_full_when_dependency_added(tmp_path, monkeypatch):
    (tmp_path / 'a.py').write_text('from package import child', encoding='utf-8')
    manager = GraphManager(tmp_path)
    manager.sync('codex')
    parser = ast.parse
    parsed = []
    def count(source, filename='<unknown>', **kwargs):
        parsed.append(filename)
        return parser(source, filename=filename, **kwargs)
    monkeypatch.setattr(ast, 'parse', count)
    unchanged = manager.sync('codex')
    assert unchanged.scan_stats['files_read'] == 0
    assert parsed == []
    (tmp_path / 'package').mkdir()
    (tmp_path / 'package/child.py').write_text('value = 1', encoding='utf-8')
    incremental = manager.sync('codex')
    assert parsed == ['package/child.py']
    assert incremental.scan_stats['files_read'] == 1
    full = manager.sync('codex', force=True)
    assert incremental.nodes == full.nodes and incremental.edges == full.edges
    assert any(e.to == 'package/child.py' for e in full.edges)
    (tmp_path / 'package/child.py').unlink()
    deleted = manager.sync('codex')
    assert 'package/child.py' not in deleted.nodes
    assert all(e.to != 'package/child.py' for e in deleted.edges)


def test_directory_intent_conflicts_in_both_directions(tmp_path):
    first, second = SyncLock(tmp_path), SyncLock(tmp_path)
    first.acquire_intent_lock('src', 'codex', '目录改动')
    with pytest.raises(LockError):
        second.acquire_intent_lock('src/a.py', 'other', '改文件')
    second.acquire_intent_lock('src-other/a.py', 'other', '不同目录')
    first.release_intent_lock('src')
    second.acquire_intent_lock('src/a.py', 'other', '改文件')
    with pytest.raises(LockError):
        first.acquire_intent_lock('src', 'codex', '目录改动')


def test_workflow_recovers_after_ledger_without_duplicate(tmp_path, monkeypatch):
    (tmp_path / 'a.py').write_text('value = 1', encoding='utf-8')
    workflow = SyncWorkflow(tmp_path)
    original = GraphManager._commit
    def fail(*args, **kwargs):
        raise OSError('模拟图谱发布前失败')
    monkeypatch.setattr(GraphManager, '_commit', fail)
    with pytest.raises(OSError):
        workflow.complete('operation-1', event())
    assert len(LedgerManager(tmp_path).read_all_events()) == 1
    (tmp_path / 'a.py').write_text('value = 2', encoding='utf-8')
    monkeypatch.setattr(GraphManager, '_commit', original)
    result = workflow.complete('operation-1', event())
    assert result['status'] == 'completed'
    assert len(LedgerManager(tmp_path).read_all_events()) == 1
    assert not workflow.pending.exists()
    assert workflow.complete('operation-1', event()) == result
    changed = event(); changed['summary'] = '不同事件'
    with pytest.raises(ValueError, match='不同事件'):
        workflow.complete('operation-1', changed)


def test_project_catalog_must_match_exact_unique_root(tmp_path):
    from archguard.adapters.codex.session_manager import CodexSessionManager, AppServerError
    class Client:
        def request(self, method, params):
            return {'data': [{'id': 'wrong', 'roots': [{'path': str(tmp_path / 'child')}]}]}
    with pytest.raises(AppServerError, match='唯一'):
        CodexSessionManager(tmp_path)._project_id(Client())



def test_workflow_repairs_only_its_partial_append_and_advances_read_cursor(tmp_path, monkeypatch):
    from archguard.sync.cursor import CursorManager
    from archguard.sync.schemas import LedgerEvent
    session = CursorManager(tmp_path).start_session('codex')
    payload = event(); payload['source_ai_ide'] = 'codex'
    original = LedgerManager.append_event
    def partial(self, data):
        self.ledger_file.parent.mkdir(parents=True, exist_ok=True)
        value = LedgerEvent.model_validate(dict(data, version='v0001')).model_dump_json(by_alias=True).encode()
        self.ledger_file.write_bytes(value[:30])
        raise OSError('模拟写入中断')
    monkeypatch.setattr(LedgerManager, 'append_event', partial)
    workflow = SyncWorkflow(tmp_path)
    with pytest.raises(OSError): workflow.complete('partial', payload, session)
    monkeypatch.setattr(LedgerManager, 'append_event', original)
    workflow.complete('partial', payload, session)
    assert len(LedgerManager(tmp_path).read_all_events()) == 1
    assert CursorManager(tmp_path).read_cursor('codex').sessions[session].last_read_line == 1


def test_queue_orders_commits_and_recovers_without_resending(tmp_path, monkeypatch):
    from tests.control_helpers import authorize
    authorize(tmp_path)
    from archguard import dispatch_queue
    from archguard.storage import atomic_json, metadata_path
    from types import SimpleNamespace
    ids = ['a'*40, 'b'*40]
    calls = []
    monkeypatch.setattr(dispatch_queue, 'get_result', lambda root, key: SimpleNamespace(audit_id=key))
    class Manager:
        def audit(self, report): calls.append(('audit', report.audit_id))
        def recover(self, report): calls.append(('recover', report.audit_id))
    for key in ids: dispatch_queue.enqueue(tmp_path, key, launch=False)
    dispatch_queue.enqueue(tmp_path, ids[0], launch=False)
    atomic_json(metadata_path(tmp_path,'jobs',ids[0],'dispatch.json'), {'status':'running','thread_id':'b','turn_id':'t'})
    dispatch_queue.drain(tmp_path, Manager())
    dispatch_queue.drain(tmp_path, Manager())
    assert calls == [('recover', ids[0]), ('audit', ids[1])]
    assert all(dispatch_queue.status(tmp_path, key)['queue']['status']=='completed' for key in ids)


def test_python_manual_semantics_survive_rescan(tmp_path):
    (tmp_path / 'a.py').write_text('value = 1', encoding='utf-8')
    manager = GraphManager(tmp_path)
    graph = manager.sync('codex')
    from archguard.sync.schemas import GraphEdge
    graph.edges.append(GraphEdge(from_='a.py', to='external:api', type='api_call'))
    graph.api_endpoints = [{'path':'/example'}]
    manager.update_graph(graph, 'codex', 'v0001')
    result=manager.sync('codex')
    assert result.api_endpoints == [{'path':'/example'}]
    assert any(e.type=='api_call' for e in result.edges)


@pytest.mark.parametrize('terminal_retry', [False, True])
def test_desktop_handoff_blocks_later_commits_until_collected(tmp_path, monkeypatch, terminal_retry):
    from tests.control_helpers import authorize
    authorize(tmp_path)
    from archguard import dispatch_queue
    from archguard.storage import atomic_json, metadata_path
    from archguard.adapters.codex.session_manager import AppServerError
    from types import SimpleNamespace
    ids = ['c' * 40, 'd' * 40]
    calls = []
    monkeypatch.setattr(dispatch_queue, 'get_result', lambda root, key: SimpleNamespace(audit_id=key))
    class Manager:
        def audit(self, report):
            calls.append(report.audit_id)
            return {'desktop_dispatch_required': True, 'thread_id': 'same-b'}
        def recover(self, report):
            raise AppServerError('原轮次已终止', rpc_error={'terminal': True})
    for key in ids:
        dispatch_queue.enqueue(tmp_path, key, launch=False)
    if terminal_retry:
        atomic_json(metadata_path(tmp_path, 'jobs', ids[0], 'dispatch.json'),
                    {'status': 'running', 'turn_id': 'old-turn'})
    dispatch_queue.drain(tmp_path, Manager())
    dispatch_queue.drain(tmp_path, Manager())
    assert calls == [ids[0]]
    assert dispatch_queue.status(tmp_path, ids[0])['queue']['status'] == 'awaiting_desktop'
    assert dispatch_queue.status(tmp_path, ids[1])['queue']['status'] == 'queued'
