import pytest
from pathlib import Path
from archguard.sync.graph import GraphManager
from archguard.sync.schemas import CodeGraph, GraphMeta

class TestGraphManager:
    """测试图谱操作"""

    @pytest.fixture
    def graph_manager(self, tmp_path: Path):
        return GraphManager(tmp_path)

    def test_init_graph(self, tmp_path: Path):
        """扫描 Python 文件生成图谱"""
        # 创建临时代码文件
        (tmp_path / "module_a.py").write_text("import os\n", encoding="utf-8")
        (tmp_path / "module_b.py").write_text("from module_a import something\n", encoding="utf-8")

        gm = GraphManager(tmp_path)
        graph = gm.init_graph("ide-1")

        assert graph.modules == ['root']
        assert len(graph.nodes) == 2
        assert len(graph.edges) == 2  # module_a -> os, module_b -> module_a

        # os is an external import, but edge is created
        assert any(e.to == "external:os" for e in graph.edges)
        assert any(e.to == "module_a.py" for e in graph.edges)

    def test_read_graph(self, graph_manager):
        """读取图谱"""
        # 此时还没有图谱
        graph = graph_manager.read_graph()
        assert graph.meta.version == "v0000"

    def test_update_graph_and_append_changelog(self, graph_manager):
        """增量更新和日志追加"""
        meta = GraphMeta(
            version="v0001",
            last_updated="2023-10-01T10:00:00Z",
            updated_by="agent-1",
            total_nodes=0,
            total_edges=0
        )
        graph = CodeGraph(
            meta=meta,
            modules=[],
            nodes={},
            edges=[]
        )

        # 这个操作需要一个旧图谱存在才能正确比较，不严格也行
        graph_manager.update_graph(graph, "ide-2", "v0002")

        # 验证读取
        new_graph = graph_manager.read_graph()
        assert new_graph.meta.updated_by == "ide-2"

        # 验证 changelog
        content = graph_manager.changelog_file.read_text(encoding="utf-8")
        import json
        entry = json.loads(content)
        assert entry['trigger_version'] == 'v0002'
        assert entry['source_ai_ide'] == 'ide-2'
