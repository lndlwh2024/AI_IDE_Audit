"""宿主 B 用量快照；未知不填零，累计不重复相加。"""
import hashlib
import time
import json
import os
from pathlib import Path
from archguard.storage import metadata_path, atomic_json, read_json, transaction

FIELDS = ('inputTokens', 'outputTokens', 'cachedInputTokens', 'reasoningOutputTokens', 'totalTokens')


def rollout_snapshot(root, client, thread_id):
    """兼容读取宿主返回的指定 B 日志；仅保留 token 字段，不保存对话。"""
    thread = client.request('thread/read', {'threadId': thread_id, 'includeTurns': False})['thread']
    if thread.get('id') != thread_id or Path(thread['cwd']).resolve() != Path(root).resolve():
        raise ValueError('B 用量日志的项目或任务不符')
    raw_path = thread['path']
    prefix = chr(92) * 2 + '?' + chr(92)
    if raw_path.startswith(prefix + 'UNC' + chr(92)):
        raw_path = chr(92) * 2 + raw_path[len(prefix) + 4:]
    elif raw_path.startswith(prefix):
        raw_path = raw_path[len(prefix):]
    log = Path(raw_path)
    home = Path(os.environ.get('CODEX_HOME', str(Path.home() / '.codex'))).resolve()
    if log.is_symlink() or not log.resolve().is_relative_to(home):
        raise ValueError('B 用量日志路径或大小不受支持')
    mapping = dict(zip(FIELDS, ('input_tokens', 'output_tokens', 'cached_input_tokens',
                               'reasoning_output_tokens', 'total_tokens')))
    cache_path = metadata_path(root, 'usage-cache', hashlib.sha256(thread_id.encode()).hexdigest() + '.json')
    cached = read_json(cache_path, {})
    stat = log.stat()
    fingerprint = [str(log.resolve()), stat.st_dev, stat.st_ino]
    if cached.get('fingerprint') != fingerprint or cached.get('offset', 0) > stat.st_size:
        cached = {}
    if cached.get('offset'):
        with log.open('rb') as check:
            check.seek(max(0, cached['offset'] - 256))
            if hashlib.sha256(check.read(min(256, cached['offset']))).hexdigest() != cached.get('tail_hash'):
                cached = {}
    latest, current, baseline, turns = cached.get('latest'), cached.get('current'), cached.get('baseline'), cached.get('turns', {})
    verified = False
    offset = cached.get('offset', 0)
    with log.open('rb') as stream:
        first = json.loads(stream.readline())
        if first.get('type') != 'session_meta':
            raise ValueError('用量日志缺少宿主身份头')
        header = first.get('payload', {})
        if header.get('id') != thread_id or Path(header.get('cwd', '')).resolve() != Path(root).resolve():
            raise ValueError('B 日志头不匹配')
        verified = True
        stream.seek(offset)
        for line in iter(stream.readline, b''):
            if not line.endswith(b'\n'):
                break  # 正在追加的半行不作为证据。
            offset = stream.tell()
            entry = json.loads(line)
            payload = entry.get('payload', {})
            if entry.get('type') == 'session_meta':
                if payload.get('id') != thread_id or Path(payload['cwd']).resolve() != Path(root).resolve():
                    raise ValueError('B 日志头不匹配')
                verified = True
            if not verified:
                continue
            if entry.get('type') == 'turn_context' and payload.get('turn_id') != current:
                current = payload.get('turn_id')
                baseline = latest
            if entry.get('type') != 'event_msg' or payload.get('type') != 'token_count':
                continue
            counters = (payload.get('info') or {}).get('total_token_usage')
            if not counters:
                continue
            last_request = (payload.get('info') or {}).get('last_token_usage')
            if latest is None and current and last_request and all(
                    counters.get(v) == last_request.get(v) for v in mapping.values()):
                baseline = {k: 0 for k in FIELDS}
            previous = latest
            latest = {k: counters.get(v) for k, v in mapping.items()}
            if any(type(n) is not int or n < 0 for n in latest.values()):
                raise ValueError('B 用量计数格式不受支持')
            if previous and any(latest[k] < previous[k] for k in FIELDS):
                baseline = None  # 计数器回退，不能推算本轮消耗。
            if current:
                # 首个可见轮次缺少前置计数时，不把累计值强行算作本轮。
                turns[current] = {k: latest[k] - baseline[k] if baseline is not None
                                  and latest[k] >= baseline[k] else None for k in FIELDS}
    if not verified or latest is None:
        raise ValueError('B 日志没有可用 token 统计')
    turns = dict(list(turns.items())[-200:])
    with log.open('rb') as check:
        check.seek(max(0, offset - 256))
        tail_hash = hashlib.sha256(check.read(min(256, offset))).hexdigest()
    atomic_json(cache_path, {'tail_hash':tail_hash, 'fingerprint':fingerprint, 'offset':offset, 'latest':latest, 'current':current, 'baseline':baseline, 'turns':turns})
    return {'counts': latest, 'per_turn': turns, 'status': 'observed',
            'source': 'codex-rollout-token_count', 'compatibility': '宿主日志格式不稳定，失败显示未知',
            'observed_at': time.time()}


def path(root, thread_id):
    return metadata_path(root, 'usage', hashlib.sha256(thread_id.encode()).hexdigest() + '.json')


def capture(root, client, thread_id):
    """只查询指定 B，不用账户统计替代项目用量。"""
    try:
        value = client.request('account/usage/read', {'threadId': thread_id}).get('threadUsage')
        if not value or value.get('threadId') != thread_id:
            raise ValueError('宿主未返回指定 B 用量')
        groups = value.get('groups', [])
        counts = {field: (sum(g[field] for g in groups) if groups and all(
            type(g.get(field)) is int and g[field] >= 0 for g in groups) else None) for field in FIELDS}
        if counts['totalTokens'] is None:
            raise ValueError('宿主未返回有效线程总量')
        return {'counts': counts, 'source': 'account/usage/read:thread', 'observed_at': time.time(),
                'status': 'observed' if counts['totalTokens'] is not None else 'unknown'}
    except Exception as exc:
        try:
            return rollout_snapshot(root, client, thread_id)
        except Exception as fallback_error:
            reason = str(exc) + '; ' + str(fallback_error)
        return {'counts': {f: None for f in FIELDS}, 'status': 'unknown', 'reason': reason,
                'source': 'account/usage/read:thread', 'observed_at': time.time()}


def save(root, thread_id, turn_id, audit_id, before, after, kind='audit'):
    with transaction(root, 'usage'):
        record = read_json(path(root, thread_id), {'thread_id': thread_id, 'turns': {}})
        delta = {}
        for field in FIELDS:
            old = (before or {}).get('counts', {}).get(field)
            new = after.get('counts', {}).get(field)
            delta[field] = new - old if (before or {}).get('source') == after.get('source') and type(old) is int and type(new) is int and new >= old else None
        observed_turn = after.get('per_turn', {}).get(turn_id)
        if observed_turn and observed_turn.get('totalTokens') is not None:
            delta = observed_turn
        record['turns'][turn_id] = {'turn_id': turn_id, 'audit_id': audit_id, 'kind': kind,
            'counts': delta, 'status': 'observed_interval' if delta['totalTokens'] is not None else 'unknown',
            'note': '宿主前后快照区间差值，可能存在统计延迟；不等同账单', 'before': {k:v for k,v in (before or {}).items() if k != 'per_turn'}, 'after': {k:v for k,v in after.items() if k != 'per_turn'}}
        if after.get('status') == 'observed':
            record['latest'] = after
        atomic_json(path(root, thread_id), record)
        return record['turns'][turn_id]


def notification(root, params):
    thread_id, turn_id = params['threadId'], params['turnId']
    value = params['tokenUsage']
    with transaction(root, 'usage'):
        record = read_json(path(root, thread_id), {'thread_id': thread_id, 'turns': {}})
        # 原始通知按轮次覆盖保存；last 不是整个轮次，total 也不能逐通知相加。
        record.setdefault('notifications', {})[turn_id] = value
        atomic_json(path(root, thread_id), record)


def report(root):
    records = [read_json(p) for p in metadata_path(root, 'usage').glob('*.json')]
    totals = [r.get('latest', {}).get('counts', {}).get('totalTokens') for r in records]
    known = [n for n in totals if type(n) is int]
    observed = {field: [r.get('latest', {}).get('counts', {}).get(field) for r in records] for field in FIELDS}
    return {'scope': '仅本项目已记录的 B，不含 A、费用或剩余额度',
            'counting': 'cachedInput 是 input 的子集，reasoningOutput 是 output 的子集，不与总量重复相加',
            'observed_counts': {field: sum(n for n in values if type(n) is int) if any(type(n) is int for n in values) else None for field, values in observed.items()},
            'observed_total_tokens': sum(known) if known else None,
            'coverage': '已记录快照，可能不完整', 'threads': records}


def refresh_current(root):
    """查询当前原生 B 的累计快照，不运行模型或扫描源码。"""
    session = read_json(metadata_path(root, 'session.json'), {})
    thread_id = session.get('thread_id')
    if not thread_id:
        return report(root)
    from archguard.adapters.codex.session_manager import CodexSessionManager
    from archguard.adapters.codex.desktop_bridge import verify_thread
    manager = CodexSessionManager(root)
    try:
        with manager.client_factory() as client:
            verify_thread(manager, client, thread_id, include_turns=False)
            snapshot = capture(root, client, thread_id)
    except Exception as exc:
        snapshot = {'status': 'unknown', 'reason': str(exc), 'observed_at': time.time()}
    with transaction(root, 'usage'):
        record = read_json(path(root, thread_id), {'thread_id': thread_id, 'turns': {}})
        record['last_attempt'] = snapshot
        if snapshot['status'] == 'observed':
            record['latest'] = snapshot
            for turn_id, counts in snapshot.get('per_turn', {}).items():
                old = record['turns'].get(turn_id, {'turn_id': turn_id, 'kind': 'native_turn', 'audit_id': None})
                if counts['totalTokens'] is not None or turn_id not in record['turns']:
                    record['turns'][turn_id] = dict(old, counts=counts, status='observed' if counts['totalTokens'] is not None else 'unknown')
        atomic_json(path(root, thread_id), record)
    return report(root)
