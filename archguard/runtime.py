"""应用编排与持久化：首次封存输入，之后所有查询读取同一提交证据。"""
import hashlib
import json
import re
from pathlib import Path
import git
from archguard.storage import metadata_path, read_json, atomic_json, atomic_text, transaction
from archguard.sync.prompts import get_pending_prompts
from archguard.sync.ledger import LedgerManager
from archguard.sync.graph import GraphManager
from archguard.core.engine import run_audit, AuditResult
from archguard.core.report_generator import generate_report


def _key(audit_id):
    if not re.fullmatch(r'[a-f0-9]{40,64}', audit_id):
        raise ValueError('审计标识必须是完整提交 SHA')
    return audit_id


def get_result(project_root, audit_id=None):
    """纯读取；未生成结果时明确失败，不隐式运行审计。"""
    path = metadata_path(project_root, 'results', 'history', _key(audit_id) + '.json') if audit_id else metadata_path(project_root, 'results', 'latest.json')
    value = read_json(path)
    if value is None:
        raise FileNotFoundError('尚无对应审计结果，请先运行 archguard audit')
    return AuditResult.model_validate(value)


def prepare_commit(project_root, measurement_ids=None):
    from archguard.sync.workflow import SyncWorkflow
    with transaction(project_root, 'workflow'):
        SyncWorkflow(project_root).recover()
        return _prepare_commit(project_root, measurement_ids)


def _prepare_commit(project_root, measurement_ids=None):
    """在 commit 前固定暂存树，供 post-commit 匹配，不提前猜测提交 SHA。"""
    repo = git.Repo(project_root)
    try:
        base = repo.head.commit.hexsha
    except ValueError:
        base = None
    with transaction(project_root):
        pending = get_pending_prompts(project_root)
        from archguard.project_control import status
        events = LedgerManager(project_root).read_all_events()[status(project_root).get('ledger_floor', 0):]
        for identifier in measurement_ids or []:
            if not re.fullmatch(r'[0-9a-f]{32}', identifier):
                raise ValueError('非法用量标识')
            record = read_json(metadata_path(project_root, 'usage-phases', identifier + '.json'), {})
            if record.get('role') != 'A' or record.get('base_commit') != base:
                raise ValueError('用量阶段不属于当前 A 开发基线')
        batch = {'usage_measurement_ids': list(measurement_ids or []), 'base_commit': base, 'tree': repo.git.write_tree(),
                 'prompts': [p for p in pending if 'base_commit' in p and p['base_commit'] == base],
                 'ledger_events': [e.model_dump(mode='json', by_alias=True) for e in events
                                   if e.git.base_commit == base and e.git.head_commit is None],
                 'declared_graph': GraphManager(project_root).read_graph().model_dump(mode='json', by_alias=True)}
        atomic_json(metadata_path(project_root, 'prepared.json'), batch)
        return batch


def audit_project(project_root, commit_hash=None):
    root = Path(project_root).resolve()
    repo = git.Repo(root)
    head = repo.commit(commit_hash) if commit_hash else repo.head.commit
    sha = head.hexsha
    # 显式历史标识仅用于已创建任务的恢复，不开放任意历史新审计。
    snapshot_file = metadata_path(root, 'jobs', sha, 'input.json')
    if sha != repo.head.commit.hexsha and not snapshot_file.exists():
        raise ValueError('只能为最新提交创建审计任务')
    with transaction(root):
        snapshot = read_json(snapshot_file)
        if snapshot is None:
            base = head.parents[0].hexsha if head.parents else None
            prepared = read_json(metadata_path(root, 'prepared.json'), {})
            diagnostics = []
            if prepared.get('tree') == head.tree.hexsha and prepared.get('base_commit') == base:
                prompts, events = prepared['prompts'], prepared['ledger_events']
                declared_graph = prepared.get('declared_graph', {})
                # 封存准备之后、真正提交之前补充的同基线需求仍属于本轮。
                known = {p.get('id') for p in prompts}
                prompts = prompts + [p for p in get_pending_prompts(root)
                                     if p.get('base_commit') == base and p.get('id') not in known]
            else:
                declared_graph = {}
                # 直接 git commit 的兼容路径仅绑定明确记录于父提交之后的需求。
                prompts = [p for p in get_pending_prompts(root) if 'base_commit' in p and p['base_commit'] == base]
                try:
                    events = [e.model_dump(mode='json', by_alias=True) for e in LedgerManager(root).read_all_events()
                              if e.git.head_commit == sha]
                except ValueError as exc:
                    events = []
                    diagnostics.append({'component': 'ledger', 'error': str(exc)})
                if not events:
                    diagnostics.append({'component': 'ledger', 'error': '没有提交前封存批次或明确 head_commit 申报'})
            previous = read_json(metadata_path(root, 'jobs', base, 'input.json'), {}) if base else {}
            snapshot = {'head_commit': sha, 'base_commit': base, 'prompts': prompts, 'ledger_events': events,
                        'declared_graph': declared_graph, 'declared_graph_before': previous.get('declared_graph', {}),
                        'diagnostics': diagnostics, 'usage_measurement_ids': prepared.get('usage_measurement_ids', []) if prepared.get('tree') == head.tree.hexsha and prepared.get('base_commit') == base else []}
            snapshot['input_hash'] = hashlib.sha256(json.dumps(snapshot, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
            atomic_json(snapshot_file, snapshot)
        expected = snapshot.get('input_hash')
        contents = {key: value for key, value in snapshot.items() if key != 'input_hash'}
        if expected != hashlib.sha256(json.dumps(contents, sort_keys=True, ensure_ascii=False).encode()).hexdigest():
            raise ValueError('封存输入校验失败，不能继续使用被修改的审计证据')
        # 输入先持久化再移除已封存 ID，崩溃后重试不会消费新需求。
        ids = {p.get('id') for p in snapshot['prompts'] if p.get('id')}
        pending = get_pending_prompts(root)
        remaining = [p for p in pending if p.get('id') not in ids]
        if remaining != pending:
            atomic_json(metadata_path(root, 'prompts', 'archived', sha + '.json'), snapshot['prompts'])
            atomic_json(metadata_path(root, 'prompts', 'pending.json'), remaining)
        history = metadata_path(root, 'results', 'history', sha + '.json')
        saved = read_json(history)
        if saved is None:
            result = run_audit(root, sha, snapshot)
            saved = result.model_dump(mode='json')
            atomic_json(history, saved)
            atomic_text(metadata_path(root, 'reports', sha + '.md'), generate_report(saved))
        else:
            result = AuditResult.model_validate(saved)
        # 旧任务恢复不覆盖最新提交的 latest 指针。
        if repo.head.commit.hexsha == sha:
            atomic_json(metadata_path(root, 'results', 'latest.json'), saved)
        return result


def save_b_input(root, report, message, developer_instructions=''):
    """留存待发送的完整模型输入；准备记录不代表宿主已接收。"""
    from archguard.delivery import payload_manifest
    value = {'audit_id':report.audit_id,'message':message,'developer_instructions':developer_instructions,
             'manifest':payload_manifest(report),'state':'prepared_not_delivery_receipt'}
    digest = hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True).encode()).hexdigest()
    path = metadata_path(root,'jobs',report.audit_id,'b-inputs',digest+'.json')
    if not path.exists():
        atomic_json(path,value)
    return str(path)
