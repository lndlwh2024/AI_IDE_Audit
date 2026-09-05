import pytest
from pathlib import Path
from archguard.sync.cursor import CursorManager

class TestCursorManager:
    """测试游标管理"""
    
    @pytest.fixture
    def cursor_manager(self, tmp_path: Path):
        return CursorManager(tmp_path)
        
    def test_read_nonexistent_cursor(self, cursor_manager):
        """读取不存在的游标文件，返回空游标"""
        cursor = cursor_manager.read_cursor("ide-1")
        assert cursor.ai_ide_id == "ide-1"
        assert len(cursor.sessions) == 0
        
    def test_update_cursor(self, cursor_manager):
        """更新游标会话"""
        cursor_manager.update_cursor("ide-1", "session-1", "v0001", 1)
        
        cursor = cursor_manager.read_cursor("ide-1")
        assert "session-1" in cursor.sessions
        assert cursor.sessions["session-1"].last_read_version == "v0001"
        assert cursor.sessions["session-1"].last_read_line == 1
        
    def test_multiple_sessions(self, cursor_manager):
        """多会话独立追踪"""
        cursor_manager.update_cursor("ide-1", "session-1", "v0001", 1)
        cursor_manager.update_cursor("ide-1", "session-2", "v0002", 2)
        
        cursor = cursor_manager.read_cursor("ide-1")
        assert len(cursor.sessions) == 2
        assert cursor.sessions["session-1"].last_read_version == "v0001"
        assert cursor.sessions["session-2"].last_read_version == "v0002"
