import pytest
import time
from pathlib import Path
from archguard.sync.lock import SyncLock, LockError
from datetime import datetime, timezone, timedelta

class TestSyncLock:
    """测试锁机制"""
    
    @pytest.fixture
    def lock_manager(self, tmp_path: Path):
        return SyncLock(tmp_path)
        
    def test_acquire_and_release_lock(self, lock_manager):
        """获取和释放锁"""
        # 获取锁
        assert lock_manager.acquire_cursor_lock("ide-1") is True
        
        # 释放锁
        lock_manager.release_cursor_lock("ide-1")
        
        # 释放后可以再次获取
        assert lock_manager.acquire_cursor_lock("ide-2") is True
        
    def test_duplicate_lock_fails(self, lock_manager):
        """重复获取同一个锁应失败"""
        assert lock_manager.acquire_graph_lock("ide-1") is True
        
        with pytest.raises(LockError):
            lock_manager.acquire_graph_lock("ide-2")
            
    def test_expired_lock(self, lock_manager):
        """过期锁可以被重新获取"""
        # 模拟创建一个过期的锁
        lock_path = lock_manager.collab_locks_dir / "cursor-ide-1.lock.json"
        
        from archguard.sync.schemas import LockFile
        expired_time = (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat()
        lock_data = LockFile(
            locked_by="ide-old", 
            locked_at=expired_time, 
            expires_at=expired_time
        )
        lock_manager._create_lock(lock_path, lock_data)
        
        # 获取锁应该成功，因为旧锁已过期会被清理
        assert lock_manager.acquire_cursor_lock("ide-1") is True
