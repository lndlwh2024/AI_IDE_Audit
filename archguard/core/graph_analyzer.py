import logging
from typing import Any
from pydantic import BaseModel, Field

# 初始化日志，用于模块内的日志记录
logger = logging.getLogger(__name__)

class GraphAnalysisResult(BaseModel):
    """
    图谱分析结果模型，使用 Pydantic v2 进行数据验证。
    """
    has_topology_changes: bool = Field(default=False, description="是否存在拓扑结构的变化")
    nodes_added: list[str] = Field(default_factory=list, description="新增的节点列表")
    nodes_removed: list[str] = Field(default_factory=list, description="移除的节点列表")
    edges_added: list[dict] = Field(default_factory=list, description="新增的依赖边列表")
    edges_removed: list[dict] = Field(default_factory=list, description="移除的依赖边列表")
    cross_module_violations: list[dict] = Field(default_factory=list, description="跨模块非法依赖引入列表")
    cycles_detected: list[list[str]] = Field(default_factory=list, description="检测到的循环依赖列表")
    orphan_nodes: list[str] = Field(default_factory=list, description="检测到的孤立节点列表")
    affected_modules: list[str] = Field(default_factory=list, description="受变更影响的模块列表")


def detect_topology_changes(old_graph: dict, new_graph: dict) -> dict:
    """
    纯集合运算：计算两个图谱之间的节点/边差异。
    
    为什么这样设计：通过集合差集运算，能快速、安全地找出增删的节点和边，避免复杂的遍历比较。
    """
    old_nodes = set(old_graph.get("nodes", {}).keys())
    new_nodes = set(new_graph.get("nodes", {}).keys())
    
    nodes_added = list(new_nodes - old_nodes)
    nodes_removed = list(old_nodes - new_nodes)
    
    # 构建边的唯一标识，用于集合运算
    def edge_key(edge: dict) -> tuple:
        return (edge.get("from"), edge.get("to"), edge.get("type"))
        
    old_edges = {edge_key(e): e for e in old_graph.get("edges", [])}
    new_edges = {edge_key(e): e for e in new_graph.get("edges", [])}
    
    old_edge_keys = set(old_edges.keys())
    new_edge_keys = set(new_edges.keys())
    
    edges_added = [new_edges[k] for k in (new_edge_keys - old_edge_keys)]
    edges_removed = [old_edges[k] for k in (old_edge_keys - new_edge_keys)]
    
    return {
        "nodes_added": nodes_added,
        "nodes_removed": nodes_removed,
        "edges_added": edges_added,
        "edges_removed": edges_removed
    }


def check_cross_module_dependencies(graph: dict, new_edges: list[dict]) -> list[dict]:
    """
    检查新增边是否跨越了已定义的模块边界。
    检测分层边界击穿（如跨模块引入非法依赖）。
    """
    violations = []
    nodes = graph.get("nodes", {})
    for edge in new_edges:
        from_node = edge.get("from")
        to_node = edge.get("to")
        
        from_module = nodes.get(from_node, {}).get("module")
        to_module = nodes.get(to_node, {}).get("module")
        
        # 边界条件：仅当源节点和目标节点都属于已知模块且分属不同模块时，才视为可能违规
        if from_module and to_module and from_module != to_module:
            violations.append({
                "from_file": from_node,
                "to_file": to_node,
                "from_module": from_module,
                "to_module": to_module,
                "edge_type": edge.get("type")
            })
            
    return violations


def detect_cycles(graph: dict) -> list[list[str]]:
    """
    使用 DFS（深度优先搜索）检测有向图中的环。
    
    为什么这样设计：通过维护一个递归栈，可以精确找出哪些节点构成了循环依赖。
    """
    adj_list = {}
    nodes = graph.get("nodes", {}).keys()
    for n in nodes:
        adj_list[n] = []
        
    for edge in graph.get("edges", []):
        u, v = edge.get("from"), edge.get("to")
        if u in adj_list:
            adj_list[u].append(v)
            
    visited = set()
    rec_stack = set()
    path = []
    cycles = []
    
    def dfs(node: str):
        visited.add(node)
        rec_stack.add(node)
        path.append(node)
        
        for neighbor in adj_list.get(node, []):
            if neighbor not in visited:
                dfs(neighbor)
            elif neighbor in rec_stack:
                # 当相邻节点在当前递归栈中，说明找到了一个环路
                cycle_start = path.index(neighbor)
                cycles.append(path[cycle_start:].copy())
                
        rec_stack.remove(node)
        path.pop()

    for node in list(adj_list.keys()):
        if node not in visited:
            dfs(node)
            
    return cycles
    

def get_orphan_nodes(graph: dict) -> list[str]:
    """
    检测孤立节点（没有任何连接边的节点）。
    """
    nodes = set(graph.get("nodes", {}).keys())
    connected_nodes = set()
    for edge in graph.get("edges", []):
        connected_nodes.add(edge.get("from"))
        connected_nodes.add(edge.get("to"))
        
    return list(nodes - connected_nodes)


def analyze_graph_changes(diff_result: Any, current_graph: dict, previous_graph: dict = None) -> GraphAnalysisResult:
    """
    分析 Diff 引入的依赖变动与现有图谱拓扑的差异。
    """
    logger.info("开始执行图谱拓扑变更分析")
    
    if previous_graph is None:
        previous_graph = {"nodes": {}, "edges": []}
        
    topo_diff = detect_topology_changes(previous_graph, current_graph)
    
    edges_added = topo_diff["edges_added"]
    cross_violations = check_cross_module_dependencies(current_graph, edges_added)
    
    cycles = detect_cycles(current_graph)
    orphans = get_orphan_nodes(current_graph)
    
    # 提取所有受本次变更影响的模块
    affected_modules = set()
    nodes_info = current_graph.get("nodes", {})
    
    # 根据增删的节点，提取关联的 module 信息
    for node in topo_diff["nodes_added"] + topo_diff["nodes_removed"]:
        mod = nodes_info.get(node, {}).get("module")
        if mod:
            affected_modules.add(mod)
            
    has_changes = bool(
        topo_diff["nodes_added"] or 
        topo_diff["nodes_removed"] or 
        topo_diff["edges_added"] or 
        topo_diff["edges_removed"]
    )
    
    logger.info("图谱拓扑分析完成，是否存在变更：%s", has_changes)
    
    return GraphAnalysisResult(
        has_topology_changes=has_changes,
        nodes_added=topo_diff["nodes_added"],
        nodes_removed=topo_diff["nodes_removed"],
        edges_added=topo_diff["edges_added"],
        edges_removed=topo_diff["edges_removed"],
        cross_module_violations=cross_violations,
        cycles_detected=cycles,
        orphan_nodes=orphans,
        affected_modules=list(affected_modules)
    )
