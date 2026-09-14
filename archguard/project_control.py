"""项目独立授权与暂停；没有有效授权时默认不工作。"""
import getpass
import hashlib
import platform
import time
from contextlib import contextmanager
from pathlib import Path
from archguard.storage import metadata_path, read_json, atomic_json, transaction


def identity(root):
    return {'root': str(Path(root).resolve()), 'host': hashlib.sha256(
        (platform.node() + '\0' + getpass.getuser()).encode()).hexdigest()}


def status(root):
    try:
        state = read_json(metadata_path(root, 'project-control.json'), {})
        if (state.get('identity') != identity(root) or not isinstance(state.get('project_id'), str) or not state.get('project_id')
                or any(type(state.get(k)) is not int or state[k] < 0 for k in ('revision', 'epoch'))
                or state.get('status') not in ('declined', 'pending_a', 'enabled', 'paused')):
            return {'status': 'unselected', 'revision': 0}
        return state
    except (ValueError, OSError, TypeError, AttributeError):
        return {'status': 'unselected', 'revision': 0, 'reason': '授权记录不可用'}


def require(root, initializing=False):
    state = status(root)
    if state['status'] not in (('enabled', 'pending_a') if initializing else ('enabled',)):
        raise PermissionError('当前项目未开启 IDE_Audit，或正在等待 A 同步；请查询项目状态')
    return state


@contextmanager
def guarded(root, initializing=False):
    # 先检查，未授权的读取不能创建目录。锁内再次检查，避免暂停与操作竞争。
    require(root, initializing)
    with transaction(root, 'project-control'):
        yield require(root, initializing)


def choose(root, project_id, enabled, confirmed=False):
    if not confirmed or not project_id:
        raise PermissionError('需要用户明确选择当前项目，不能把安装或沉默视为授权')
    with transaction(root, 'project-control'):
        old = status(root)
        # 已开启项目重复确认不能重置同步状态或队列。
        if enabled and old.get('project_id') == project_id and old['status'] == 'enabled':
            return old
        state = dict(old, identity=identity(root), project_id=project_id,
                     status='pending_a' if enabled else 'declined', archive_on_refresh=True,
                     revision=old['revision'] + 1, epoch=old.get('epoch', 0) + 1, changed_at=time.time())
        atomic_json(metadata_path(root, 'project-control.json'), state)
        return state


def pause(root):
    with transaction(root, 'project-control'):
        old = status(root)
        if old['status'] in ('unselected', 'declined', 'paused'):
            return old
        state = dict(old, status='paused', revision=old['revision'] + 1, epoch=old.get('epoch', 0) + 1, changed_at=time.time())
        atomic_json(metadata_path(root, 'project-control.json'), state)
        from datetime import datetime, timezone
        with transaction(root, 'leases'):
            for lease_path in metadata_path(root, 'collab', 'locks').glob('intent-*.lock.json'):
                lease = read_json(lease_path, {})
                if lease.get('project_controlled'):
                    atomic_json(lease_path, dict(lease, expires_at=datetime.now(timezone.utc).isoformat()))
    # 状态先关闭；待发队列保留，旧工作者也必须检查状态。
    return dict(state, stopping='已停止新派发；正在运行的轮次等待中断或收尾')


def resume(root):
    with transaction(root, 'project-control'):
        old = status(root)
        if old['status'] not in ('paused', 'pending_a', 'enabled'):
            raise PermissionError('项目尚未授权，请先明确开启')
        if old['status'] != 'paused':
            return old
        state = dict(old, status='pending_a', archive_on_refresh=True, revision=old['revision'] + 1, changed_at=time.time())
        atomic_json(metadata_path(root, 'project-control.json'), state)
        return state


def verify_project(root):
    from archguard.adapters.codex.session_manager import CodexSessionManager
    manager = CodexSessionManager(root)
    with manager.client_factory() as client:
        actual = manager._project_id(client)
    if status(root).get('project_id') != actual:
        raise PermissionError('当前 Codex 项目归属已变化，需重新授权')


def refresh_a(root, ide_id, session_id=None, thread_id=None):
    """只有开发端注册此入口；同步到当前状态，不逐提交补造历史。"""
    import git
    from archguard.sync.graph import GraphManager
    from archguard.sync.cursor import CursorManager
    from archguard.sync.workflow import SyncWorkflow
    with guarded(root, initializing=True) as state:
        state = dict(state, archive_on_refresh=state['status'] == 'pending_a' and state.get('archive_on_refresh', False))
        atomic_json(metadata_path(root, 'project-control.json'),
                    dict(state, status='pending_a', revision=state['revision'] + 1))
        verify_project(root)
        with transaction(root, 'workflow'):
            SyncWorkflow(root).recover()
            cursors = CursorManager(root)
            if thread_id:
                session_id = cursors.start_session(ide_id, thread_id)
            elif session_id not in cursors.read_cursor(ide_id).sessions:
                session_id = None
            repo = git.Repo(root)
            head = repo.head.commit.hexsha if repo.head.is_valid() else None
            previous = state.get('checkpoint', {}).get('head')
            interval = {'from': previous, 'to': head, 'history': 'unknown'}
            if head and previous:
                try:
                    if repo.is_ancestor(repo.commit(previous), repo.commit(head)):
                        interval['history'] = 'linear_or_merged'
                        interval['commits'] = repo.git.rev_list(previous + '..' + head).splitlines()
                except (ValueError, git.GitCommandError):
                    pass
            graph = GraphManager(root).sync(ide_id)
            session_id = session_id or cursors.start_session(ide_id, thread_id)
            # 暂停前未封存需求保留为历史，不能授权恢复后的新提交。
            if state.get('archive_on_refresh', False):
                with transaction(root):
                    pending = metadata_path(root, 'prompts', 'pending.json')
                    values = read_json(pending, [])
                    if values:
                        atomic_json(metadata_path(root, 'prompts', 'archived',
                                    'resume-' + str(state['revision']) + '.json'), values)
                        atomic_json(pending, [])
                    prepared = metadata_path(root, 'prepared.json')
                    previous_batch = read_json(prepared)
                    if previous_batch:
                        atomic_json(metadata_path(root, 'prompts', 'archived',
                                    'prepared-resume-' + str(state['revision']) + '.json'), previous_batch)
                        atomic_json(prepared, {})
            from archguard.sync.ledger import LedgerManager
            floor = (len(LedgerManager(root).read_all_events()) if state.get('archive_on_refresh', False)
                     else state.get('ledger_floor', 0))
            checkpoint = {'head': head, 'dirty': repo.is_dirty(untracked_files=True),
                          'graph_version': graph.meta.version, 'interval': interval,
                          'session_id': session_id, 'updated_at': time.time()}
            updated = dict(state, status='enabled', archive_on_refresh=False, revision=state['revision'] + 2, checkpoint=checkpoint, ledger_floor=floor)
            atomic_json(metadata_path(root, 'project-control.json'), updated)
            return {'session_id': session_id, 'graph': graph.model_dump(mode='json', by_alias=True),
                    'project': updated}
