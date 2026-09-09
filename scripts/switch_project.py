"""插件之外的旧项目切换工具：默认预检，保留原始资产与独立回滚记录。"""
import argparse
import copy
import json
import shutil
from pathlib import Path
from uuid import uuid4
from datetime import datetime, timezone
from legacy_sync_assets import manifest
from archguard.sync.schemas import CodeGraph, LedgerEvent
from archguard.storage import atomic_json, atomic_text, metadata_path
from archguard.adapters.codex.installer import install_to_project, uninstall_from_project


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


def switch(root, apply=False):
    root = Path(root).resolve(strict=True)
    source = root / '.ai-sync'
    before = manifest(source)
    events, graph = convert(source)
    targets = [root / base / 'skills/dual-agent-sync' for base in ('.agents', '.codex', '.agent')]
    targets = [p for p in targets if p.exists()]
    for path in targets:
        if path.is_symlink() or path.resolve() != path or not path.resolve().is_relative_to(root):
            raise ValueError('旧 Skill 是链接，请先人工停用该项目链接；不修改链接指向的共享 Skill')
    for name in ('collab', 'codegraph'):
        p = metadata_path(root, name)
        if p.exists() and any(p.iterdir()):
            raise ValueError('目标已有协同资产，禁止覆盖')
    result = {'status': 'planned', 'events': len(events), 'nodes': len(graph.nodes),
              'disable_skills': [p.relative_to(root).as_posix() for p in targets],
              'source_retained': True, 'requires_a_graph_refresh': True}
    if not apply:
        return result
    record = metadata_path(root, 'cutover', uuid4().hex)
    record.mkdir(parents=True)
    shutil.copytree(source, record / 'source-backup')
    if manifest(record / 'source-backup') != before or manifest(source) != before:
        raise ValueError('备份或源资产发生变化，已停止切换')
    saved = {}
    for rel in ('AGENTS.md', '.codex/config.toml'):
        p = root / rel
        saved[rel] = p.read_text(encoding='utf-8') if p.exists() else None
    receipt = dict(result, project_root=str(root), original_config=saved, status='prepared', source_hashes=before)
    atomic_json(record / 'receipt.json', receipt)
    moved = []
    try:
        for p in targets:
            dest = record / 'disabled-skills' / p.relative_to(root)
            dest.parent.mkdir(parents=True, exist_ok=True)
            p.rename(dest)
            moved.append((p, dest))
        atomic_text(metadata_path(root, 'collab', 'ledger.jsonl'), ''.join(e.model_dump_json(by_alias=True)+'\n' for e in events))
        atomic_json(metadata_path(root, 'codegraph', 'graph.json'), graph.model_dump(mode='json', by_alias=True))
        from archguard.sync.ledger import LedgerManager
        LedgerManager(root).rebuild_views()
        install_to_project(root)
        receipt['installed_config'] = {rel: manifest_file(root / rel) for rel in saved}
        receipt['status'] = 'completed'
        atomic_json(record / 'receipt.json', receipt)
    except Exception:
        for p, dest in reversed(moved):
            if not p.exists(): dest.rename(p)
        receipt['status'] = 'needs_rollback'
        atomic_json(record / 'receipt.json', receipt)
        raise
    return dict(result, status='completed', receipt=str(record / 'receipt.json'))


def manifest_file(path):
    import hashlib
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None


def rollback(receipt_path):
    receipt_path = Path(receipt_path).resolve(strict=True)
    receipt = json.loads(receipt_path.read_text(encoding='utf-8'))
    root = Path(receipt['project_root']).resolve(strict=True)
    record = receipt_path.parent
    if not record.is_relative_to(root / '.ide_audit/cutover'):
        raise ValueError('回滚记录不属于目标项目')
    if receipt.get('status') == 'rolled_back':
        return {'status': 'rolled_back'}
    for rel, old in receipt['original_config'].items():
        if rel not in ('AGENTS.md', '.codex/config.toml'):
            raise ValueError('非法配置回滚路径')
        path = root / rel
        if not path.resolve().is_relative_to(root):
            raise ValueError('配置回滚路径重定向')
        current = path.read_text(encoding='utf-8') if path.exists() else None
        expected = receipt.get('installed_config', {}).get(rel)
        if current != old and (expected is None or manifest_file(path) != expected):
            raise ValueError('切换后配置被修改，须合并后再回滚')
    uninstall_from_project(root)
    for rel, old in receipt['original_config'].items():
        path = root / rel
        if old is None:
            path.unlink(missing_ok=True)
        else:
            atomic_text(path, old)
    for rel in receipt['disable_skills']:
        if rel not in [base + '/skills/dual-agent-sync' for base in ('.agents', '.codex', '.agent')]:
            raise ValueError('非法 Skill 回滚路径')
        original = root / rel
        saved = record / 'disabled-skills' / rel
        if saved.exists():
            if original.exists() or not original.parent.resolve().is_relative_to(root):
                raise ValueError('Skill 恢复目标已有内容或被重定向')
            saved.rename(original)
    for name in ('collab', 'codegraph'):
        source = metadata_path(root, name)
        destination = record / 'rolled-back-assets' / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        if source.exists():
            if not source.resolve().is_relative_to(root) or not destination.resolve().is_relative_to(record):
                raise ValueError('资产回滚路径越界')
            source.rename(destination)
    receipt['status'] = 'rolled_back'
    atomic_json(receipt_path, receipt)
    return {'status': 'rolled_back', 'new_assets_retained': True}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='旧项目独立切换，默认只读预检')
    parser.add_argument('--project-root')
    parser.add_argument('--rollback', help='切换 receipt.json 路径')
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    if not args.project_root and not args.rollback:
        parser.error('需要 --project-root 或 --rollback')
    print(json.dumps(rollback(args.rollback) if args.rollback else switch(args.project_root, args.apply), ensure_ascii=False, indent=2))
