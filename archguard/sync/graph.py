import logging
import ast
from pathlib import Path
from datetime import datetime, timezone
from typing import Dict, List
from .schemas import CodeGraph, GraphMeta, GraphNode, GraphEdge, GraphChangelogEntry, GraphDiff

logger = logging.getLogger(__name__)

class GraphManager:
    """
    基于 Python AST 进行静态分析并提取引用关系的全局代码图谱维护工具。
    同时负责记录所有的图谱变动日志，形成可追溯的链路。
    """
    def __init__(self, project_root: Path):
        self.project_root = Path(project_root)
        self.graph_dir = self.project_root / '.ide_audit' / 'codegraph'
        self.graph_file = self.graph_dir / 'graph.json'
        self.changelog_file = self.graph_dir / 'graph.changelog.jsonl'
        self.graph_dir.mkdir(parents=True, exist_ok=True)
        
    def read_graph(self) -> CodeGraph:
        """加载当前图谱"""
        if not self.graph_file.exists():
            return CodeGraph(
                meta=GraphMeta(version="v0000", last_updated="", updated_by="system", total_nodes=0, total_edges=0),
                modules=[], nodes={}, edges=[]
            )
        try:
            return CodeGraph.model_validate_json(self.graph_file.read_text(encoding='utf-8'))
        except Exception as e:
            logger.error(f"读取图谱时发生错误: {e}")
            raise

    def init_graph(self, ide_id: str) -> CodeGraph:
        """全量初始化扫描，解析项目下全部 Python 文件的 imports 关系"""
        nodes: Dict[str, GraphNode] = {}
        edges: List[GraphEdge] = []
        modules: List[str] = []
        
        # 扫描规则：忽略隐藏目录和常规无关目录
        for py_file in self.project_root.rglob("*.py"):
            if ".ide_audit" in py_file.parts or "venv" in py_file.parts or ".git" in py_file.parts:
                continue
                
            module_name = py_file.relative_to(self.project_root).as_posix()
            modules.append(module_name)
            
            try:
                content = py_file.read_text(encoding='utf-8')
                tree = ast.parse(content)
                imports = []
                for node in ast.walk(tree):
                    if isinstance(node, ast.Import):
                        for n in node.names:
                            imports.append(n.name)
                    elif isinstance(node, ast.ImportFrom) and node.module:
                        imports.append(node.module)
                
                nodes[module_name] = GraphNode(
                    module=module_name,
                    purpose="auto-analyzed module",
                    imports=imports
                )
                
                # 构建边关系
                for imp in imports:
                    edges.append(GraphEdge(from_=module_name, to=imp, type="imports"))
            except SyntaxError as se:
                logger.warning(f"语法错误，跳过分析 {py_file}: {se}")
            except Exception as e:
                logger.warning(f"无法解析 {py_file} 依赖: {e}")
                
        meta = GraphMeta(
            version="v0001",
            last_updated=datetime.now(timezone.utc).isoformat(),
            updated_by=ide_id,
            total_nodes=len(nodes),
            total_edges=len(edges)
        )
        
        graph = CodeGraph(meta=meta, modules=modules, nodes=nodes, edges=edges)
        self.graph_file.write_text(graph.model_dump_json(by_alias=True, indent=2), encoding='utf-8')
        
        # 追加变更记录
        diff = GraphDiff(
            nodes_added=list(nodes.keys()), 
            nodes_removed=[], 
            edges_added=[{"from": e.from_, "to": e.to, "type": e.type} for e in edges], 
            edges_removed=[]
        )
        self.append_changelog(GraphChangelogEntry(
            timestamp=datetime.now(timezone.utc).isoformat(),
            source_ai_ide=ide_id,
            action="init",
            trigger_version="v0001",
            summary="Initial graph scan via AST",
            diff=diff
        ))
        return graph

    def get_graph_diff(self, old_graph: CodeGraph, new_graph: CodeGraph) -> GraphDiff:
        """比对新旧图谱状态，生成变更统计"""
        old_nodes = set(old_graph.nodes.keys())
        new_nodes = set(new_graph.nodes.keys())
        
        old_edges = {(e.from_, e.to, e.type) for e in old_graph.edges}
        new_edges = {(e.from_, e.to, e.type) for e in new_graph.edges}
        
        return GraphDiff(
            nodes_added=list(new_nodes - old_nodes),
            nodes_removed=list(old_nodes - new_nodes),
            edges_added=[{"from": e[0], "to": e[1], "type": e[2]} for e in new_edges - old_edges],
            edges_removed=[{"from": e[0], "to": e[1], "type": e[2]} for e in old_edges - new_edges]
        )

    def update_graph(self, graph: CodeGraph, ide_id: str, trigger_version: str):
        """应用增量更改，同时更新元数据并写入 Changelog，调用者需保证获得排他锁"""
        old_graph = self.read_graph()
        diff = self.get_graph_diff(old_graph, graph)
        
        graph.meta.last_updated = datetime.now(timezone.utc).isoformat()
        graph.meta.updated_by = ide_id
        graph.meta.total_nodes = len(graph.nodes)
        graph.meta.total_edges = len(graph.edges)
        
        self.graph_file.write_text(graph.model_dump_json(by_alias=True, indent=2), encoding='utf-8')
        
        self.append_changelog(GraphChangelogEntry(
            timestamp=datetime.now(timezone.utc).isoformat(),
            source_ai_ide=ide_id,
            action="update",
            trigger_version=trigger_version,
            summary=f"Incremental graph update driven by {trigger_version}",
            diff=diff
        ))

    def append_changelog(self, entry: GraphChangelogEntry):
        """追加记录至图谱变更日志文件"""
        with open(self.changelog_file, 'a', encoding='utf-8') as f:
            f.write(entry.model_dump_json(by_alias=True) + "\n")
