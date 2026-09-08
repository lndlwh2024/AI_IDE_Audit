import pytest
from archguard.core.graph_analyzer import analyze_graph_changes

class TestGraphAnalyzer:
    """测试图谱分析"""

    def test_no_changes(self):
        """无变化时的空结果"""
        current_graph = {"nodes": {}, "edges": []}
        prev_graph = {"nodes": {}, "edges": []}

        result = analyze_graph_changes({}, current_graph, prev_graph)
        assert result.has_topology_changes is False
        assert len(result.nodes_added) == 0
        assert len(result.edges_added) == 0

    def test_detect_topology_changes(self):
        """检测拓扑变化（节点/边新增删除）"""
        prev_graph = {
            "nodes": {"mod_a": {"module": "mod_a"}},
            "edges": []
        }
        current_graph = {
            "nodes": {
                "mod_a": {"module": "mod_a"},
                "mod_b": {"module": "mod_b"}
            },
            "edges": [{"from": "mod_b", "to": "mod_a", "type": "imports"}]
        }

        result = analyze_graph_changes({}, current_graph, prev_graph)
        assert result.has_topology_changes is True
        assert "mod_b" in result.nodes_added
        assert len(result.edges_added) == 1

    def test_cross_module_dependencies(self):
        """检测跨模块依赖"""
        current_graph = {
            "nodes": {
                "file1": {"module": "module_A"},
                "file2": {"module": "module_B"}
            },
            "edges": [{"from": "file1", "to": "file2", "type": "imports"}]
        }
        current_graph['forbidden_dependencies'] = [['module_A', 'module_B']]
        # 明确声明禁止的模块关系，普通跨模块依赖不应直接视为违规。
        prev_graph = {
            "nodes": current_graph["nodes"],
            "edges": []
        }

        result = analyze_graph_changes({}, current_graph, prev_graph)
        assert len(result.cross_module_violations) == 1
        assert result.cross_module_violations[0]["from_module"] == "module_A"

    def test_detect_cycles(self):
        """检测循环依赖"""
        current_graph = {
            "nodes": {
                "a": {"module": "mod"},
                "b": {"module": "mod"},
                "c": {"module": "mod"}
            },
            "edges": [
                {"from": "a", "to": "b", "type": "imports"},
                {"from": "b", "to": "c", "type": "imports"},
                {"from": "c", "to": "a", "type": "imports"}
            ]
        }

        result = analyze_graph_changes({}, current_graph, current_graph) # Using same for prev to isolate cycle logic
        # has_topology_changes is False here, but cycles_detected should populate
        assert len(result.cycles_detected) > 0
        assert "a" in result.cycles_detected[0]
