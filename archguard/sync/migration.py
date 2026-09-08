"""旧协同资产的可校验迁移：不覆盖旧备份，不删除源数据。"""
import hashlib
import json
import shutil
from pathlib import Path
from uuid import uuid4
from archguard.storage import metadata_path, atomic_json, transaction
from .schemas import CodeGraph, CursorFile, LedgerEvent


def manifest(directory):
    result = {}
    for path in Path(directory).rglob('*'):
        if path.is_symlink() or (hasattr(path, 'is_junction') and path.is_junction()):
            raise ValueError('迁移资产包含链接或 junction，不能自动复制')
        if path.is_file():
            result[path.relative_to(directory).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    return result


def validate_assets(collab, graph):
    ledger = collab / 'ledger.jsonl'
    if ledger.exists():
        text = ledger.read_text(encoding='utf-8')
        if text and not text.endswith('\n'):
            raise ValueError('旧账本末行缺少换行，无法确认是否写入完成；请先修复源资产再迁移')
        for i, line in enumerate(text.splitlines(), 1):
            event = json.loads(line)
            if event.get('version') != f'v{i:04d}':
                raise ValueError(f'旧账本第 {i} 行版本不连续')
            # 旧协议中 graph_impact 可缺省，校验补缺省但迁移保留原字节。
            LedgerEvent.model_validate(dict(event, graph_impact=event.get('graph_impact', {})))
    for path in (collab / 'cursors').glob('*.json'):
        data = json.loads(path.read_text(encoding='utf-8'))
        if 'sessions' in data:
            CursorFile.model_validate(data)
        elif not isinstance(data, dict):
            raise ValueError('旧游标格式无效')
    path = graph / 'graph.json'
    if path.exists():
        CodeGraph.model_validate_json(path.read_text(encoding='utf-8'))


def migrate_assets(project_root, dry_run=False):
    root = Path(project_root).resolve()
    source = root / '.ai-sync'
    if not source.exists():
        return {'status': 'not_needed'}
    if source.is_symlink() or source.resolve() != source:
        raise ValueError('旧目录不能重定向')
    before = manifest(source)
    legacy = (source / 'ledger.jsonl').exists()
    if legacy and (source / 'collab/ledger.jsonl').exists():
        raise ValueError('旧目录同时含 V1/V2 账本，须先确认数据来源')
    collab = source if legacy else source / 'collab'
    graph = source / 'codegraph'
    validate_assets(collab, graph)
    for name in ('collab', 'codegraph'):
        target = metadata_path(root, name)
        if target.exists() and any(target.iterdir()):
            raise ValueError(f'目标 {name} 已有资产，禁止合并覆盖')
    result = {'status': 'planned', 'source_format': 'v1' if legacy else 'v2',
              'files': before, 'source_retained': True}
    if dry_run:
        return result
    with transaction(root, 'migration'):
        for name in ('collab', 'codegraph'):
            target = metadata_path(root, name)
            if target.exists() and any(target.iterdir()):
                raise ValueError('目标在计划后发生变化，请重新预检')
        record = metadata_path(root, 'migrations', uuid4().hex)
        backup = record / 'source-backup'
        stage = record / 'staged'
        shutil.copytree(source, backup)
        if manifest(source) != before or manifest(backup) != before:
            raise ValueError('迁移期间源数据变化或备份不一致，已中止')
        stage.mkdir()
        if legacy:
            (stage / 'collab').mkdir()
            for name in ('ledger.jsonl', 'AUDIT_LOG.md', 'PROJECT_STATE.md'):
                if (backup / name).exists():
                    shutil.copy2(backup / name, stage / 'collab' / name)
            for name in ('cursors', 'locks'):
                if (backup / name).exists():
                    shutil.copytree(backup / name, stage / 'collab' / name)
        else:
            shutil.copytree(backup / 'collab', stage / 'collab') if (backup / 'collab').exists() else (stage / 'collab').mkdir()
        shutil.copytree(backup / 'codegraph', stage / 'codegraph') if (backup / 'codegraph').exists() else (stage / 'codegraph').mkdir()
        validate_assets(stage / 'collab', stage / 'codegraph')
        atomic_json(record / 'manifest.json', dict(result, status='prepared'))
        published = []
        try:
            for name in ('collab', 'codegraph'):
                target = metadata_path(root, name)
                if target.exists():
                    target.rmdir()  # 预检确认只能是空目录。
                origin = stage / name
                if not origin.resolve().is_relative_to(metadata_path(root).resolve()):
                    raise ValueError('暂存路径越界')
                origin.rename(target)
                published.append(name)
            atomic_json(record / 'manifest.json', dict(result, status='completed'))
        except Exception:
            for name in reversed(published):
                metadata_path(root, name).rename(stage / name)
            atomic_json(record / 'manifest.json', dict(result, status='rolled_back'))
            raise
        return dict(result, status='completed', backup=str(backup))
