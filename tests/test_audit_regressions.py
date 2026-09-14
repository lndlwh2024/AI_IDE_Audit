"""将交接审计中的真实失败样例固定为跨模块回归测试。"""
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import git
import pytest
from archguard.core.diff_analyzer import analyze_commit
from archguard.core.engine import run_audit
from archguard.runtime import audit_project, prepare_commit, get_result
from archguard.sync.prompts import record_prompt, get_pending_prompts
from archguard.sync.graph import GraphManager
from archguard.sync.ledger import LedgerManager


@pytest.fixture
def repo(tmp_path):
    repo = git.Repo.init(tmp_path)
    with repo.config_writer() as config:
        config.set_value('user', 'name', 'test')
        config.set_value('user', 'email', 'test@example.invalid')
        config.set_value('core', 'autocrlf', 'false')
    (tmp_path / 'service.py').write_text('value = 1\n', encoding='utf-8')
    repo.index.add(['service.py'])
    repo.index.commit('baseline')
    return repo


def event(base=None):
    return {'timestamp': '2026-09-09T00:00:00Z', 'project': 'test', 'source_ai_ide': 'test-ide',
            'event_type': 'code_update', 'git': {'base_commit': base},
            'scope': {'modules': [], 'files_changed': [{'file': 'service.py', 'lines': ['1-3']}], 'docs_changed': []},
            'graph_impact': {}, 'context': {'requirement_background': '', 'problem_background': '', 'solution': '',
            'current_status': '', 'remaining_issues': [], 'next_steps': [], 'risks': []},
            'verification': {'tests_run': [], 'tests_not_run': [], 'result': ''}, 'summary': '更新服务'}


def changed(repo):
    root = Path(repo.working_tree_dir)
    (root / 'service.py').write_text('import asyncio\nvalue = 2\nsql = "CREATE TABLE demo (id INT)"\n', encoding='utf-8')
    repo.index.add(['service.py'])


def test_patch_and_content_rules(repo):
    changed(repo)
    repo.index.commit('change')
    facts = analyze_commit(repo.working_tree_dir)
    assert (facts.total_additions, facts.total_deletions) == (3, 1)
    assert facts.files[0].added_lines == [1, 2, 3]
    assert facts.files[0].deleted_lines == [1]
    result = run_audit(repo.working_tree_dir)
    assert {'DB_SCHEMA_DDL', 'EXECUTION_MODEL_CHANGE'} <= {s['rule_id'] for s in result.architecture_signals}
    assert not (Path(repo.working_tree_dir) / '.ide_audit').exists()


def test_repeat_audit_keeps_prompts_and_does_not_consume_new(repo):
    root = repo.working_tree_dir
    record_prompt(root, '本轮需求')
    LedgerManager(root).append_event(event(repo.head.commit.hexsha))
    changed(repo)
    declaration = event()
    declaration['git'] = {'base_commit':repo.head.commit.hexsha}
    LedgerManager(root).append_event(declaration)
    prepare_commit(root)
    repo.index.commit('change')
    first = audit_project(root)
    assert first.analysis_status == 'complete'
    record_prompt(root, '下一轮需求')
    second = audit_project(root)
    assert first == second
    assert [p['text'] for p in get_pending_prompts(root)] == ['下一轮需求']
    assert get_result(root, first.audit_id) == first


def test_manual_old_commit_cannot_consume_new_prompts(repo):
    record_prompt(repo.working_tree_dir, '尚未提交的新需求')
    result = audit_project(repo.working_tree_dir)
    assert not result.prompts
    assert get_pending_prompts(repo.working_tree_dir)
    assert result.analysis_status == 'partial'


def test_historical_ledger_does_not_mask_new_change(repo):
    root = repo.working_tree_dir
    old = event()
    old['git']['head_commit'] = repo.head.commit.hexsha
    LedgerManager(root).append_event(old)
    changed(repo)
    repo.index.commit('new')
    result = audit_project(root)
    assert result.ledger_verification['undeclared_files'] == ['service.py']


def test_actual_graph_detects_cycle_and_tracks_document_nodes(repo):
    root = Path(repo.working_tree_dir)
    (root / 'a.py').write_text('import b\n', encoding='utf-8')
    (root / 'b.py').write_text('import a\n', encoding='utf-8')
    repo.index.add(['a.py', 'b.py'])
    repo.index.commit('cycle')
    GraphManager(root).sync('test')
    (root / 'README.md').write_text('文档\n', encoding='utf-8')
    repo.index.add(['README.md'])
    repo.index.commit('docs')
    graph = run_audit(root).graph_analysis
    assert graph['nodes_added'] == ['README.md']
    assert any(set(c) == {'a.py', 'b.py'} for c in graph['cycles_detected'])


def test_concurrent_ledger_versions_unique(tmp_path):
    def append(_):
        return LedgerManager(tmp_path).append_event(event()).version
    with ThreadPoolExecutor(max_workers=4) as pool:
        versions = list(pool.map(append, range(12)))
    assert sorted(versions) == [f'v{i:04d}' for i in range(1, 13)]
    assert len(LedgerManager(tmp_path).read_all_events()) == 12


def test_wrong_line_range_detected(repo):
    from archguard.core.ledger_analyzer import verify_ledger_consistency
    changed(repo)
    repo.index.commit('change')
    declaration = event()
    declaration['scope']['files_changed'][0]['lines'] = ['999-999']
    result = verify_ledger_consistency(analyze_commit(repo.working_tree_dir), [declaration])
    assert not result.is_consistent
    assert result.line_deviations


def test_sealed_inputs_detect_tampering(repo):
    root = Path(repo.working_tree_dir)
    record_prompt(root, '原需求')
    changed(repo)
    declaration = event()
    declaration['git'] = {'base_commit':repo.head.commit.hexsha}
    LedgerManager(root).append_event(declaration)
    prepare_commit(root)
    repo.index.commit('change')
    first = audit_project(root)
    path = root / '.ide_audit/jobs' / first.audit_id / 'input.json'
    payload = json.loads(path.read_text(encoding='utf-8'))
    payload['prompts'][0]['text'] = '被替换的需求'
    path.write_text(json.dumps(payload), encoding='utf-8')
    with pytest.raises(ValueError, match='校验失败'):
        audit_project(root)


def test_non_python_declarations_are_frozen_not_read_from_later_workspace(repo):
    from archguard.sync.schemas import CodeGraph
    root = Path(repo.working_tree_dir)
    (root / 'web.js').write_text('export const value = 1;\n', encoding='utf-8')
    manager = GraphManager(root)
    graph = manager.sync('test')
    graph.nodes['web.js'].purpose = '前端入口'
    manager.update_graph(graph, 'test', 'v0001')
    repo.index.add(['web.js'])
    record_prompt(root, '新增前端入口')
    declaration = event()
    declaration['git'] = {'base_commit':repo.head.commit.hexsha}
    LedgerManager(root).append_event(declaration)
    prepare_commit(root)
    repo.index.commit('web')
    first = audit_project(root)
    graph.nodes['web.js'].purpose = '后续变更'
    manager.update_graph(graph, 'test', 'v0002')
    assert audit_project(root).declared_graph['nodes']['web.js']['purpose'] == '前端入口'
    assert first.graph_after['supported_languages'] == ['python']


def test_multiprocess_ledger_no_lost_events(tmp_path):
    import subprocess
    import sys
    payload = tmp_path / 'event.json'
    payload.write_text(json.dumps(event()), encoding='utf-8')
    code = ('import json,sys; from pathlib import Path; from archguard.sync.ledger import LedgerManager; '
            'm=LedgerManager(sys.argv[1]); e=json.loads(Path(sys.argv[2]).read_text()); '
            '[m.append_event(e) for _ in range(4)]')
    processes = [subprocess.Popen([sys.executable, '-c', code, str(tmp_path), str(payload)],
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE) for _ in range(3)]
    for process in processes:
        out, err = process.communicate(timeout=40)
        assert process.returncode == 0, err.decode(errors='replace')
    assert [e.version for e in LedgerManager(tmp_path).read_all_events()] == [f'v{i:04d}' for i in range(1, 13)]


def test_rename_delete_and_binary_facts(repo):
    root = Path(repo.working_tree_dir)
    repo.git.mv('service.py', 'renamed service.py')
    (root / 'binary.bin').write_bytes(b'\x00\xff\x00')
    repo.index.add(['binary.bin'])
    repo.index.commit('rename and binary')
    files = {f.path: f for f in analyze_commit(root).files}
    assert files['renamed service.py'].rename_from == 'service.py'
    assert files['binary.bin'].binary
    repo.git.rm('--', 'renamed service.py')
    repo.index.commit('delete')
    assert analyze_commit(root).files[0].change_type == 'D'


def test_stale_owner_cannot_release_new_lease(tmp_path):
    from archguard.sync.lock import SyncLock, LockError
    first, second = SyncLock(tmp_path), SyncLock(tmp_path)
    first.acquire_intent_lock('service.py', 'first', '编辑')
    path = next((tmp_path / '.ide_audit/collab/locks').glob('intent-*.json'))
    payload = json.loads(path.read_text(encoding='utf-8'))
    payload['expires_at'] = '2000-01-01T00:00:00+00:00'
    path.write_text(json.dumps(payload), encoding='utf-8')
    second.acquire_intent_lock('service.py', 'second', '编辑')
    with pytest.raises(LockError):
        first.release_intent_lock('service.py')
    assert path.exists()
    second.release_intent_lock('service.py')
