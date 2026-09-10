"""提交后持久队列；独立后台进程串行派发，主开发窗口无需等待模型。"""
import os
import subprocess
import sys
import time
from pathlib import Path
from archguard.storage import metadata_path, read_json, atomic_json, transaction
from archguard.runtime import get_result, _key
from archguard import project_control as control
from archguard.adapters.codex.session_manager import CodexSessionManager


def enqueue(root, audit_id, launch=True):
    path = metadata_path(root, 'queue', _key(audit_id) + '.json')
    with control.guarded(root) as authorization, transaction(root, 'queue'):
        if not path.exists():
            atomic_json(path, {'audit_id': audit_id, 'created_at': time.time(), 'status': 'queued', 'epoch': authorization['epoch']})
    if launch:
        start_worker(root)
    return read_json(path)


def start_worker(root):
    if control.status(root)["status"] != "enabled":
        return
    log = metadata_path(root, 'queue', 'worker.log')
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open('ab') as output:
        subprocess.Popen([sys.executable, '-m', 'archguard.dispatch_queue', str(Path(root).resolve())],
                stdin=subprocess.DEVNULL, stdout=output, stderr=output, close_fds=True,
                creationflags=(subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS) if os.name == 'nt' else 0,
                start_new_session=os.name != 'nt')


def status(root, audit_id):
    identifier = _key(audit_id)
    pending = []
    for p in metadata_path(root, 'queue').glob('*.json'):
        value = read_json(p)
        if value.get('status') == 'awaiting_desktop' and value.get('epoch') == control.status(root).get('epoch') and control.status(root)['status'] == 'enabled':
            pending.append(value)
    pending.sort(key=lambda e: e['created_at'])
    return {'audit_id': identifier, 'desktop_pending': [e['audit_id'] for e in pending],
            'queue': read_json(metadata_path(root, 'queue', identifier + '.json'), {}),
            'dispatch': read_json(metadata_path(root, 'jobs', identifier, 'dispatch.json'), {}),
            'session': read_json(metadata_path(root, 'session.json'), {})}


def drain(root, manager=None):
    if control.status(root)["status"] != "enabled":
        return
    manager = manager or CodexSessionManager(root)
    # 每次唤醒等待前一个进程退出后再检查，避免队列尾部入队丢失唤醒。
    with transaction(root, 'dispatch-worker', timeout=3600):
        entries = [(read_json(p), p) for p in metadata_path(root, 'queue').glob('*.json')]
        entries.sort(key=lambda item: item[0]['created_at'])
        for entry, path in entries:
            if control.status(root)["status"] != "enabled":
                return
            if entry.get('epoch') != control.status(root).get('epoch', 0):
                if entry['status'] != 'completed':
                    atomic_json(path, dict(entry, status='held_after_pause'))
                continue
            if entry['status'] == 'awaiting_desktop':
                return
            if entry['status'] in ('completed', 'needs_attention', 'failed', 'held_after_pause'):
                continue
            audit_id = entry['audit_id']
            atomic_json(path, dict(entry, status='running'))
            state_file = metadata_path(root, 'jobs', audit_id, 'dispatch.json')
            state = read_json(state_file, {})
            try:
                report = get_result(root, audit_id)
                result = None
                if state.get('status') in ('sending', 'running', 'failed'):
                    # 只回收原轮次结果；绝不因为连接中断而盲目重新发送。
                    deadline = time.monotonic() + 600
                    while True:
                        if control.status(root).get('epoch') != entry.get('epoch') or control.status(root)['status'] != 'enabled':
                            raise PermissionError('项目已暂停，旧任务需明确恢复')
                        try:
                            manager.recover(report)
                            break
                        except Exception as exc:
                            if getattr(exc, 'rpc_error', {}).get('terminal'):
                                # 原轮次确定终止，最多进行一次自动重试。
                                if entry.get('retry_count', 0):
                                    raise
                                entry['retry_count'] = 1
                                atomic_json(path, dict(entry, status='running'))
                                result = manager.audit(report)
                                break
                            if not state.get('turn_id') or time.monotonic() >= deadline:
                                raise
                            time.sleep(2)
                else:
                    result = manager.audit(report)
                if isinstance(result, dict) and result.get('desktop_dispatch_required'):
                    atomic_json(path, dict(entry, status='awaiting_desktop'))
                    return
                atomic_json(path, dict(entry, status='completed'))
            except Exception as exc:
                atomic_json(path, dict(entry, status='needs_attention', error=str(exc)))
                # 保留原状态用于 recover，不让一个失败任务隐藏后续排队记录。
                return


def retry(root, audit_id, manager=None):
    """人工重试入口：先核验原轮次，只有确定终止或从未发送才重新排队。"""
    control.require(root)
    identifier = _key(audit_id)
    manager = manager or CodexSessionManager(root)
    report = get_result(root, identifier)
    state_file = metadata_path(root, 'jobs', identifier, 'dispatch.json')
    state = read_json(state_file, {})
    if state.get('status') in ('sending', 'running', 'failed'):
        try:
            manager.recover(report)
        except Exception as exc:
            if not getattr(exc, 'rpc_error', {}).get('terminal'):
                raise
    path = metadata_path(root, 'queue', identifier + '.json')
    entry = read_json(path, {'audit_id': identifier, 'created_at': time.time()})
    with control.guarded(root) as authorization:
        atomic_json(path, dict(entry, status='queued', epoch=authorization['epoch']))
    start_worker(root)
    return status(root, identifier)


if __name__ == '__main__':
    drain(Path(sys.argv[1]).resolve())
