import pytest
from pydantic import ValidationError
from archguard.sync.schemas import (
    LedgerEvent, GraphEdge, CodeGraph, DiagnosticRecord, GraphNode, GraphMeta
)

class TestSyncSchemas:
    """测试 sync 模块中 schemas 的定义和数据验证"""

    def test_ledger_event_creation(self):
        """测试 LedgerEvent 的创建与序列化"""
        data = {
            "version": "v0001",
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
            "summary": "Fixed a bug"
        }
        event = LedgerEvent(**data)
        assert event.version == "v0001"
        assert event.event_type == "bugfix"

    def test_ledger_event_invalid_type(self):
        """测试使用无效的 event_type 时抛出错误"""
        data = {
            "version": "v0001",
            "timestamp": "2023-10-01T10:00:00Z",
            "project": "TestProject",
            "source_ai_ide": "agent-1",
            "event_type": "invalid_type",
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
            "summary": "Invalid event"
        }
        with pytest.raises(ValidationError):
            LedgerEvent(**data)

    def test_graph_edge_alias(self):
        """测试 GraphEdge 中 from_ 的别名处理"""
        # 从字典验证，使用别名 "from"
        edge = GraphEdge(**{"from": "moduleA", "to": "moduleB", "type": "imports"})
        assert edge.from_ == "moduleA"
        
        # 也可以使用模型本身提供的 by_alias 导出
        dumped = edge.model_dump(by_alias=True)
        assert "from" in dumped
        assert dumped["from"] == "moduleA"

    def test_diagnostic_record_optional_fields(self):
        """测试 DiagnosticRecord 的可选字段"""
        record = DiagnosticRecord(
            status="unresolved",
            symptom="Crash on startup",
            current_best_conclusion="Null pointer",
            confidence="high",
            evidence=["Log trace"],
            ruled_out=["OOM"],
            open_hypotheses=["DB connection failed"],
            next_actions=["Check DB"],
            do_not_repeat=["Restart service"],
            handoff_prompt="Please fix DB"
        )
        assert record.supersedes_version is None
        assert record.invalidated_assumption is None

    def test_code_graph_creation(self):
        """测试 CodeGraph 的完整构建"""
        meta = GraphMeta(
            version="v001",
            last_updated="2023-10-01T10:00:00Z",
            updated_by="agent-1",
            total_nodes=1,
            total_edges=0
        )
        node = GraphNode(module="mod1", purpose="test")
        graph = CodeGraph(
            meta=meta,
            modules=["mod1"],
            nodes={"mod1": node},
            edges=[]
        )
        assert graph.meta.total_nodes == 1
        assert "mod1" in graph.nodes
