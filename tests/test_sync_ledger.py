import pytest
from pathlib import Path
from archguard.sync.ledger import LedgerManager

class TestLedgerManager:
    """测试记账本操作"""
    
    @pytest.fixture
    def ledger_manager(self, tmp_path: Path):
        """提供使用临时目录初始化的 LedgerManager"""
        return LedgerManager(tmp_path)
        
    def test_get_latest_version_empty(self, ledger_manager):
        """测试空文件返回 v0000"""
        assert ledger_manager.get_latest_version() == "v0000"
        
    def test_append_event(self, ledger_manager):
        """测试追加事件并自动递增版本号"""
        event_data = {
            "timestamp": "2023-10-01T10:00:00Z",
            "project": "TestProject",
            "source_ai_ide": "agent-1",
            "event_type": "bugfix",
            "git": {},
            "scope": {"modules": [], "files_changed": [], "docs_changed": []},
            "graph_impact": {},
            "context": {
                "requirement_background": "",
                "problem_background": "",
                "solution": "",
                "current_status": "",
                "remaining_issues": [],
                "next_steps": [],
                "risks": []
            },
            "verification": {"tests_run": [], "tests_not_run": [], "result": ""},
            "summary": "First event"
        }
        
        event1 = ledger_manager.append_event(event_data)
        assert event1.version == "v0001"
        assert ledger_manager.get_latest_version() == "v0001"
        
        event_data["summary"] = "Second event"
        event2 = ledger_manager.append_event(event_data)
        assert event2.version == "v0002"
        assert ledger_manager.get_latest_version() == "v0002"
        
    def test_read_all_events(self, ledger_manager):
        """测试全量读取"""
        assert len(ledger_manager.read_all_events()) == 0
        
        event_data = {
            "timestamp": "2023-10-01T10:00:00Z",
            "project": "TestProject",
            "source_ai_ide": "agent-1",
            "event_type": "bugfix",
            "git": {},
            "scope": {"modules": [], "files_changed": [], "docs_changed": []},
            "graph_impact": {},
            "context": {
                "requirement_background": "",
                "problem_background": "",
                "solution": "",
                "current_status": "",
                "remaining_issues": [],
                "next_steps": [],
                "risks": []
            },
            "verification": {"tests_run": [], "tests_not_run": [], "result": ""},
            "summary": "First event"
        }
        ledger_manager.append_event(event_data)
        ledger_manager.append_event(event_data)
        
        events = ledger_manager.read_all_events()
        assert len(events) == 2
        assert events[0].version == "v0001"
        assert events[1].version == "v0002"
        
    def test_read_events_from_line(self, ledger_manager):
        """测试增量读取"""
        event_data = {
            "timestamp": "2023-10-01T10:00:00Z",
            "project": "TestProject",
            "source_ai_ide": "agent-1",
            "event_type": "bugfix",
            "git": {},
            "scope": {"modules": [], "files_changed": [], "docs_changed": []},
            "graph_impact": {},
            "context": {
                "requirement_background": "",
                "problem_background": "",
                "solution": "",
                "current_status": "",
                "remaining_issues": [],
                "next_steps": [],
                "risks": []
            },
            "verification": {"tests_run": [], "tests_not_run": [], "result": ""},
            "summary": "Event"
        }
        for _ in range(3):
            ledger_manager.append_event(event_data)
            
        events = ledger_manager.read_events_from_line(2)
        assert len(events) == 2
        assert events[0].version == "v0002"
        assert events[1].version == "v0003"
