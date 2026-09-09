"""协同意图租约：使用串行化管理与所有者令牌保护创建和释放。"""
import hashlib
import os
from datetime import datetime, timezone, timedelta
from uuid import uuid4
from archguard.storage import metadata_path, read_json, atomic_json, transaction
from .schemas import LockFile
from .cursor import valid_id


class LockError(RuntimeError):
    pass


class SyncLock:
    def __init__(self, project_root):
        self.project_root = project_root
        self.collab_locks_dir = metadata_path(project_root, 'collab', 'locks')
        self.graph_locks_dir = metadata_path(project_root, 'codegraph', 'locks')
        self.owned = {}

    def _create_lock(self, lock_path, lock_data):
        with transaction(self.project_root, 'leases'):
            if lock_data.scope:
                for other_path in self.collab_locks_dir.glob('intent-*.lock.json'):
                    other = read_json(other_path)
                    if (other and other.get('scope') and
                            datetime.fromisoformat(other['expires_at']) > datetime.now(timezone.utc) and
                            scopes_overlap(lock_data.scope, other['scope'])):
                        raise LockError('文件或父目录被另一有效编辑意图占用')
            previous = read_json(lock_path)
            if previous:
                expires = previous.get('expires_at')
                if not expires or datetime.fromisoformat(expires) > datetime.now(timezone.utc):
                    raise LockError('资源被另一会话占用')
            token = uuid4().hex
            atomic_json(lock_path, dict(lock_data.model_dump(), lock_id=token))
            self.owned[str(lock_path)] = token

    def _release(self, path):
        with transaction(self.project_root, 'leases'):
            current = read_json(path)
            if current:
                token = self.owned.get(str(path))
                if not token or current.get('lock_id') != token:
                    raise LockError('只能释放自己持有的锁')
                path.unlink()
            self.owned.pop(str(path), None)

    def _acquire(self, path, ide_id, scope=None, purpose=None):
        valid_id(ide_id)
        now = datetime.now(timezone.utc)
        self._create_lock(path, LockFile(locked_by=ide_id, locked_at=now.isoformat(),
            expires_at=(now + timedelta(minutes=10)).isoformat(), scope=scope, purpose=purpose))
        return True

    def acquire_cursor_lock(self, ide_id):
        valid_id(ide_id)
        return self._acquire(self.collab_locks_dir / f'cursor-{ide_id}.lock.json', ide_id)

    def release_cursor_lock(self, ide_id):
        valid_id(ide_id)
        self._release(self.collab_locks_dir / f'cursor-{ide_id}.lock.json')

    def _scope_path(self, scope):
        from archguard.core.ledger_analyzer import normalize
        scope = os.path.normcase(normalize(scope)).replace(chr(92), "/")
        return self.collab_locks_dir / ('intent-' + hashlib.sha256(scope.encode()).hexdigest() + '.lock.json')

    def acquire_intent_lock(self, scope, ide_id, purpose):
        return self._acquire(self._scope_path(scope), ide_id, scope, purpose)

    def release_intent_lock(self, scope):
        self._release(self._scope_path(scope))

    def acquire_graph_lock(self, ide_id):
        return self._acquire(self.graph_locks_dir / 'codegraph.lock.json', ide_id)

    def release_graph_lock(self):
        self._release(self.graph_locks_dir / 'codegraph.lock.json')


    def renew_intent_locks(self, scopes):
        """整批校验后续期；已过期或已被接管的租约不得复活。"""
        paths = {self._scope_path(scope) for scope in scopes}
        with transaction(self.project_root, 'leases'):
            now = datetime.now(timezone.utc)
            records = {}
            for path in paths:
                current = read_json(path)
                token = self.owned.get(str(path))
                if (not current or not token or current.get('lock_id') != token
                        or datetime.fromisoformat(current['expires_at']) <= now):
                    raise LockError('租约已失效或不属于当前会话，不能续期')
                records[path] = current
            for path, current in records.items():
                atomic_json(path, dict(current, expires_at=(now + timedelta(minutes=10)).isoformat()))


def scopes_overlap(left, right):
    from archguard.core.ledger_analyzer import normalize
    a, b = [os.path.normcase(normalize(x)).replace(chr(92), '/').rstrip('/') for x in (left, right)]
    return a == b or a.startswith(b + '/') or b.startswith(a + '/')
