"""插件之外的旧项目切换工具：默认预检，保留原始资产、单向切换。"""
import argparse
import copy
import json
from pathlib import Path
from legacy_sync_assets import manifest
from archguard.sync.schemas import CodeGraph, LedgerEvent
from archguard.storage import atomic_json, atomic_text, metadata_path
from archguard.adapters.codex.installer import install_to_project


def convert(source):
    ledger = source / 'collab/ledger.jsonl'
    if not ledger.exists():
        ledger = source / 'ledger.jsonl'
    original = [json.loads(line) for line in ledger.read_text(encoding='utf-8-sig').splitlines() if line.strip()]
    versions = {e['version']: f'v{i:04d}' for i, e in enumerate(original, 1)}
    if len(versions) != len(original):
        raise ValueError('源账本版本重复，无法确定引用关系')
    events = []
    allowed = set(LedgerEvent.model_fields['event_type'].annotation.__args__)
    for raw in original:
        e = copy.deepcopy(raw)
        e['legacy_version'] = e['version']
        e['version'] = versions[e['version']]
        if e['event_type'] not in allowed:
            e['legacy_event_type'] = e['event_type']
            e['event_type'] = 'handoff'
        scope = e.setdefault('scope', {})
        scope['files_changed'] = [({'file': x} if isinstance(x, str) else x) for x in scope.get('files_changed', [])]
        scope.setdefault('modules', []); scope.setdefault('docs_changed', [])
        scope['legacy_docs_changed'] = copy.deepcopy(scope['docs_changed'])
        scope['docs_changed'] = [x['file'] if isinstance(x, dict) else x for x in scope['docs_changed']]
        context = e.setdefault('context', {})
        for field in ('remaining_issues', 'next_steps', 'risks'):
            context.setdefault(field, [])
        for field in ('requirement_background', 'problem_background', 'solution', 'current_status'):
            context.setdefault(field, '旧记录未提供此字段')
        verification = e.setdefault('verification', {})
        verification.setdefault('tests_run', []); verification.setdefault('tests_not_run', [])
        verification.setdefault('result', '旧记录未提供验证结果')
        diagnostic = e.get('context', {}).get('diagnostic_record')
        if diagnostic and diagnostic.get('supersedes_version') in versions:
            diagnostic['supersedes_version'] = versions[diagnostic['supersedes_version']]
        impact = e.setdefault('graph_impact', {})
        for key in ('nodes_added', 'nodes_removed', 'edges_added', 'edges_removed'):
            if isinstance(impact.get(key), int):
                impact['legacy_count_' + key] = impact[key]
                impact[key] = []
                impact['legacy_details_unavailable'] = True
        e.setdefault('project', source.parent.name)
        e.setdefault('source_ai_ide', 'legacy-unknown')
        e.setdefault('timestamp', '')
        e.setdefault('git', {})
        e['legacy_git'] = copy.deepcopy(e['git'])
        if e['git'].get('head_commit') is None:
            e['git']['base_commit'] = None  # 旧未封存事件不能混入首次新开发提交。
        e.setdefault('summary', '旧记录未提供摘要，详见保留的原始内容')
        events.append(LedgerEvent.model_validate(e))
    graph = json.loads((source / 'codegraph/graph.json').read_text(encoding='utf-8-sig'))
    modules = graph.get('modules', [])
    graph['module_details'] = {m['id']: m for m in modules if isinstance(m, dict)}
    graph['modules'] = [m['id'] if isinstance(m, dict) else m for m in modules]
    for node in graph['nodes'].values():
        node.setdefault('module', node.get('module_id', 'root'))
    return events, CodeGraph.model_validate(graph)


def switch(root, apply=False, consent=False):
    """外部单向切换：保留全部旧资产，不维护回滚或双写。"""
    root = Path(root).resolve(strict=True)
    source = root / '.ai-sync'
    before = manifest(source)
    events, graph = convert(source)
    targets = [root / base / 'skills/dual-agent-sync' for base in ('.agents', '.codex', '.agent')]
    targets = [p for p in targets if p.exists()]
    for target in targets:
        if target.is_symlink() or target.resolve() != target:
            raise ValueError('旧 Skill 是链接，不能改动共享目标')
    result = {'status': 'planned', 'events': len(events), 'nodes': len(graph.nodes),
              'assets': before, 'disable_skills': [p.relative_to(root).as_posix() for p in targets],
              'source_retained': True, 'requires_a_graph_refresh': True, 'rollback': False}
    if not apply:
        return result
    if not consent:
        raise ValueError('实际切换须明确同意当前项目，使用 --apply --consent')
    from archguard.adapters.codex.session_manager import CodexSessionManager
    from archguard.project_control import choose
    manager = CodexSessionManager(root)
    with manager.client_factory() as client:
        project_id = manager._project_id(client)
    receipt_path = metadata_path(root, 'cutover', 'fast-switch.json')
    previous = json.loads(receipt_path.read_text(encoding='utf-8')) if receipt_path.exists() else None
    if previous and previous.get('source_hashes') != before:
        raise ValueError('旧资产已变化，需核对后修复转换记录；不能覆盖')
    for name in ('collab', 'codegraph'):
        target = metadata_path(root, name)
        if not previous and target.exists() and any(target.iterdir()):
            raise ValueError('已有新协同资产，禁止覆盖')
    if previous and previous.get('status') in ('awaiting_a_validation', 'awaiting_b_validation', 'completed'):
        return previous
    record = dict(result, source_hashes=before, status='converting', project_root=str(root))
    atomic_json(receipt_path, record)
    # 原始目录完整保留；新数据仅转换必要格式，不复制或删改其他业务资产。
    ledger_file = metadata_path(root, 'collab', 'ledger.jsonl')
    graph_file = metadata_path(root, 'codegraph', 'graph.json')
    ledger_text = ''.join(e.model_dump_json(by_alias=True)+'\n' for e in events)
    graph_data = graph.model_dump(mode='json', by_alias=True)
    if ledger_file.exists() and ledger_file.read_text(encoding='utf-8') != ledger_text:
        raise ValueError('新账本已有变化，需在新数据上修复，不能重跑覆盖')
    if graph_file.exists() and json.loads(graph_file.read_text(encoding='utf-8')) != graph_data:
        raise ValueError('新图谱已有变化，需在新数据上修复，不能重跑覆盖')
    atomic_text(ledger_file, ledger_text)
    atomic_json(graph_file, graph_data)
    from archguard.sync.ledger import LedgerManager
    LedgerManager(root).rebuild_views()
    choose(root, project_id, True, confirmed=True)
    install_to_project(root)
    if manifest(source) != before:
        raise ValueError('切换期间旧写入者仍在修改资产，请停止旧工作流并核对')
    # 停用入口但保留 Skill 文件，不恢复旧系统、不删除历史。
    for target in targets:
        destination = metadata_path(root, 'legacy-assets', 'disabled-skills', target.relative_to(root).as_posix())
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists():
            raise ValueError('旧入口留存位置已存在，请核对后修复')
        target.rename(destination)
    record['status'] = 'awaiting_a_validation'
    record['next'] = 'NEWS 的 A 完成图谱同步和真实提交验收；问题在新插件修复'
    atomic_json(receipt_path, record)
    return record


def finalize(root):
    root = Path(root).resolve(strict=True)
    from archguard.project_control import require
    from archguard.runtime import get_result
    from archguard.storage import read_json
    state = require(root)
    receipt = metadata_path(root, 'cutover', 'fast-switch.json')
    record = read_json(receipt)
    if not record or record.get('status') not in ('awaiting_a_validation', 'awaiting_b_validation', 'completed'):
        raise ValueError('尚未完成转换和入口切换')
    if not state.get('checkpoint', {}).get('session_id'):
        raise ValueError('必须由 A 完成接入同步')
    if manifest(root / '.ai-sync') != record['source_hashes']:
        raise ValueError('旧资产仍发生变化，请确认已停止旧写入者')
    result = get_result(root)
    dispatch = read_json(metadata_path(root, 'jobs', result.audit_id, 'dispatch.json'), {})
    if dispatch.get('status') != 'completed' or not read_json(metadata_path(root, 'verdicts', result.audit_id + '.json')):
        raise ValueError('必须先验证真实 B 审计结果')
    record.update(status='completed', validated_audit=result.audit_id, thread_id=dispatch['thread_id'])
    atomic_json(receipt, record)
    return record


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='插件外单向切换，默认只读预检，无回滚流程')
    parser.add_argument('--project-root', required=True)
    action = parser.add_mutually_exclusive_group()
    action.add_argument('--apply', action='store_true')
    action.add_argument('--finalize', action='store_true')
    parser.add_argument('--consent', action='store_true')
    args = parser.parse_args()
    result = finalize(args.project_root) if args.finalize else switch(args.project_root, args.apply, args.consent)
    print(json.dumps(result, ensure_ascii=True))
