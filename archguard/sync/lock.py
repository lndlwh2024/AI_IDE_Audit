import os
import logging
from pathlib import Path
from datetime import datetime, timezone, timedelta
from .schemas import LockFile

logger = logging.getLogger(__name__)

class LockError(Exception):
    """锁操作相关异常"""
    pass

class SyncLock:
    """
    管理三种同步锁：
    1. 游标排他锁 (Cursor Exclusive Lock)
    2. 编辑意图软锁 (Edit Intent Soft Lock)
    3. 图谱写入排他锁 (Graph Write Exclusive Lock)
    
    使用文件系统的原子操作 O_EXCL 创建锁，所有锁操作须通过 try/finally 处理。
    默认锁在 10 分钟后自动过期，过期后将强制清理。
    """
    def __init__(self, project_root: Path):
        self.project_root = Path(project_root)
        self.collab_locks_dir = self.project_root / '.ide_audit' / 'collab' / 'locks'
        self.graph_locks_dir = self.project_root / '.ide_audit' / 'codegraph' / 'locks'
        
        self.collab_locks_dir.mkdir(parents=True, exist_ok=True)
        self.graph_locks_dir.mkdir(parents=True, exist_ok=True)

    def _create_lock(self, lock_path: Path, lock_data: LockFile):
        """底层的原子锁创建机制 (O_CREAT | O_EXCL)"""
        self._cleanup_expired_lock(lock_path)
        try:
            # 必须使用 O_EXCL 以确保并发安全
            fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            with os.fdopen(fd, 'w', encoding='utf-8') as f:
                f.write(lock_data.model_dump_json(indent=2))
            logger.debug(f"成功获取锁: {lock_path}")
        except FileExistsError:
            raise LockError(f"无法获取锁 {lock_path}，文件已存在")

    def _cleanup_expired_lock(self, lock_path: Path):
        """检查并清理过期的锁文件"""
        if not lock_path.exists():
            return
        try:
            content = lock_path.read_text(encoding='utf-8')
            lock_data = LockFile.model_validate_json(content)
            if lock_data.expires_at:
                expires = datetime.fromisoformat(lock_data.expires_at)
                if datetime.now(timezone.utc) > expires:
                    lock_path.unlink()
                    logger.warning(f"清理了已过期的锁: {lock_path}")
        except Exception as e:
            logger.error(f"清理锁时出错: {e}")

    def acquire_cursor_lock(self, ide_id: str) -> bool:
        """获取游标排他锁 (Read-Merge-Write 保证安全)"""
        lock_path = self.collab_locks_dir / f"cursor-{ide_id}.lock.json"
        expires = (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat()
        lock_data = LockFile(
            locked_by=ide_id, 
            locked_at=datetime.now(timezone.utc).isoformat(), 
            expires_at=expires
        )
        self._create_lock(lock_path, lock_data)
        return True

    def release_cursor_lock(self, ide_id: str):
        """释放游标排他锁"""
        lock_path = self.collab_locks_dir / f"cursor-{ide_id}.lock.json"
        if lock_path.exists():
            lock_path.unlink()

    def acquire_intent_lock(self, scope: str, ide_id: str, purpose: str) -> bool:
        """获取编辑意图软锁 (冲突检测预警)"""
        lock_path = self.collab_locks_dir / f"{scope}.lock.json"
        expires = (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat()
        lock_data = LockFile(
            locked_by=ide_id, 
            locked_at=datetime.now(timezone.utc).isoformat(), 
            scope=scope, 
            purpose=purpose, 
            expires_at=expires
        )
        self._create_lock(lock_path, lock_data)
        return True
        
    def release_intent_lock(self, scope: str):
        """释放编辑意图软锁"""
        lock_path = self.collab_locks_dir / f"{scope}.lock.json"
        if lock_path.exists():
            lock_path.unlink()

    def acquire_graph_lock(self, ide_id: str) -> bool:
        """获取图谱排他锁，防止多智能体并发更新图谱时损坏数据"""
        lock_path = self.graph_locks_dir / "codegraph.lock.json"
        expires = (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat()
        lock_data = LockFile(
            locked_by=ide_id, 
            locked_at=datetime.now(timezone.utc).isoformat(), 
            expires_at=expires
        )
        self._create_lock(lock_path, lock_data)
        return True

    def release_graph_lock(self):
        """释放图谱排他锁"""
        lock_path = self.graph_locks_dir / "codegraph.lock.json"
        if lock_path.exists():
            lock_path.unlink()
