"""A/B 操作区间的真实宿主用量；只计已观测差值，未知不猜测。"""
from archguard import operation_log
import time
import hashlib
from uuid import uuid4
from pathlib import Path
from archguard import usage, project_control as control
from archguard.storage import metadata_path, atomic_json, read_json, transaction


def snapshot(root, thread_id):
    from archguard.adapters.codex.session_manager import CodexSessionManager
    manager = CodexSessionManager(root)
    try:
        with manager.client_factory() as client:
            thread = client.request('thread/read', {'threadId':thread_id, 'includeTurns':False})['thread']
            project = manager._project_id(client)
            if thread.get('id') != thread_id or Path(thread['cwd']).resolve() != manager.root:
                raise ValueError('用量任务目录不匹配')
            if project != control.status(root).get('project_id') or thread.get('projectId') not in (None, project):
                raise ValueError('用量任务项目不匹配')
            # 老 A 可能无 projectId；以宿主目录、当前授权项目及日志头共同验证，仅读计数。
            value = usage.capture(root, client, thread_id)
            if value.get('counts', {}).get('totalTokens') is not None:
                atomic_json(window_path(root, thread_id), {'thread_id':thread_id, 'observed_at':time.time(), 'snapshot':{k:v for k,v in value.items() if k != 'per_turn'}})
            return value
    except Exception as exc:
        return {'status':'unknown', 'counts':{f:None for f in usage.FIELDS},
                'source':'host-unavailable', 'reason':str(exc)}


def begin(root, thread_id, phase, role, audit_id=None):
    control.require(root, initializing=True)
    if phase not in ('initial_sync', 'before_edit', 'prepare_commit', 'after_commit', 'audit', 'align_updates', 'edit_lock', 'record_changes', 'graph_update', 'edit_unlock', 'dispatch'):
        raise ValueError('未知操作阶段')
    if (role == 'A' and phase == 'audit') or (role == 'B' and phase != 'audit'):
        raise ValueError('阶段与 A/B 职责不符')
    current_b = read_json(metadata_path(root, 'session.json'), {}).get('thread_id')
    if (role == 'B' and thread_id != current_b) or (role == 'A' and thread_id == current_b):
        raise ValueError('用量任务与 A/B 身份不符')
    if audit_id is not None:
        from archguard.runtime import get_result
        audit_id = get_result(root, audit_id).audit_id
    value = snapshot(root, thread_id)
    value.pop('per_turn', None)
    import git
    try:
        base_commit = git.Repo(root).head.commit.hexsha
    except (git.InvalidGitRepositoryError, ValueError):
        base_commit = None
    identifier = uuid4().hex
    atomic_json(metadata_path(root, 'usage-phases', identifier + '.json'),
                {'id':identifier, 'audit_id':audit_id, 'base_commit':base_commit, 'thread_id':thread_id, 'role':role, 'phase':phase, 'before':value, 'started_at':time.time(), 'status':'started'})
    return {'measurement_id':identifier, 'status':value['status'], 'note':'统计当前阶段的模型交互区间；本地 Python 扫描本身不调用模型'}


def finish(root, identifier, role):
    if len(identifier) != 32 or any(c not in '0123456789abcdef' for c in identifier):
        raise ValueError('非法用量标识')
    path = metadata_path(root, 'usage-phases', identifier + '.json')
    with transaction(root, 'usage-phases'):
        record = read_json(path)
        if not record or record['role'] != role:
            raise ValueError('用量区间不存在或角色不符')
        if record['status'] != 'completed':
            after = snapshot(root, record['thread_id'])
            after.pop('per_turn', None)
            before = record['before']
            counts = {}
            for field in usage.FIELDS:
                old, new = before.get('counts',{}).get(field), after.get('counts',{}).get(field)
                counts[field] = new-old if before.get('source') == after.get('source') and type(old) is int and type(new) is int and new >= old else None
            record.update(status='completed', after=after, counts=counts, finished_at=time.time())
            atomic_json(path, record)
            operation_log.write(root, 'phase_finished', measurement_id=identifier, thread_id=record['thread_id'], role=role, phase=record['phase'], counts=counts, source=after.get('source'), thread_total_tokens=after.get('counts', {}).get('totalTokens'), settlement='observed_interval' if counts.get('totalTokens') else 'unknown_or_pending')
        total = record.get('after',{}).get('counts',{}).get('totalTokens')
        observed_delta = record['counts']['totalTokens']
        n = observed_delta if observed_delta != 0 else None
        return {'role':role, 'phase':record['phase'], 'this_phase_tokens':n, 'thread_total_tokens':total,
                'observed_interval_delta':observed_delta, 'settlement':'no_new_observation' if observed_delta == 0 else 'observed_interval',
                'counts':record['counts'], 'source':record.get('after',{}).get('source'),
                'display':f"{role} · {record['phase']}：本次 {n if n is not None else '待结算/未知'} token；本窗口累计（宿主当前计数）{total if total is not None else '未知'} token",
                'scope':'累计是宿主当前计数；计数器重置前的历史不保证完整。截至最近宿主统计；包含此阶段交互携带的上下文，不含尚未结算的最终回复，不代表费用或额度百分比'}


def compact_b(root):
    full = usage.refresh_current(root)
    current = read_json(metadata_path(root,'session.json'),{}).get('thread_id')
    records = full['threads']
    record = next((r for r in records if r['thread_id'] == current), {})
    turn = next(reversed(record.get('turns',{}).values()), {}) if record.get('turns') else {}
    last = turn.get('counts',{}).get('totalTokens') or None
    total = record.get('latest',{}).get('counts',{}).get('totalTokens')
    return {'role':'B', 'this_turn_tokens':last, 'thread_total_tokens':total,
            'project_b_total_tokens':full['observed_total_tokens'],
            'display':f"B：本轮 {last if last is not None else '未知'} token；本窗口累计（宿主当前计数）{total if total is not None else '未知'} token",
            'note':'宿主统计可能延迟；只返回摘要，完整计数留存本地'}


def window_path(root, thread_id):
    return metadata_path(root, 'usage-windows', hashlib.sha256(thread_id.encode()).hexdigest() + '.json')


def window_total(root, thread_id, refresh=False):
    if not thread_id:
        return {'total':None, 'status':'未记录 A 任务身份'}
    if refresh:
        snapshot(root, thread_id)
    record = read_json(window_path(root, thread_id), {})
    return {'total':record.get('snapshot',{}).get('counts',{}).get('totalTokens'),
            'observed_at':record.get('observed_at'), 'thread_id':thread_id,
            'status':'最近观测，非实时账单' if record else '宿主未返回可用累计'}


def pending_ids(root, thread_id):
    import git
    try:
        base = git.Repo(root).head.commit.hexsha
    except ValueError:
        base = None
    return [r['id'] for p in metadata_path(root,'usage-phases').glob('*.json')
            if (r := read_json(p, {})).get('thread_id') == thread_id and r.get('base_commit') == base
            and r.get('role') == 'A' and r.get('audit_id') is None]
