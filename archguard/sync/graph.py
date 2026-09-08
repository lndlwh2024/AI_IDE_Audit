"""维护工作态图谱；先落可恢复记录，再原子提交图谱与变更日志。"""
import hashlib
from datetime import datetime, timezone
from pathlib import Path
from archguard.core.codegraph import build_graph
from archguard.core.graph_analyzer import detect_topology_changes
from archguard.storage import metadata_path, atomic_json, atomic_text, read_json, transaction
from .schemas import CodeGraph, GraphMeta, GraphDiff


class GraphManager:
    def __init__(self, project_root):
        self.project_root = Path(project_root).resolve()
        self.graph_file = metadata_path(project_root, 'codegraph', 'graph.json')
        self.graph_dir = self.graph_file.parent
        self.changelog_file = self.graph_dir / 'graph.changelog.jsonl'
        self.journal = self.graph_dir / 'pending-write.json'

    def read_graph(self):
        data = read_json(self.graph_file)
        return CodeGraph.model_validate(data) if data else CodeGraph(
            meta=GraphMeta(version='v0000', last_updated='', updated_by='system', total_nodes=0, total_edges=0),
            modules=[], nodes={}, edges=[])

    def _recover(self):
        journal = read_json(self.journal)
        if journal:
            atomic_json(self.graph_file, journal['graph'])
            atomic_text(self.changelog_file, journal['changelog'])
            self.journal.unlink()

    def sync(self, ide_id, trigger_version=None):
        with transaction(self.project_root, 'graph'):
            self._recover()
            sources = {}
            ignored = {'.git', '.ide_audit', '.ai-sync', '.pytest_cache', '.venv', 'venv', 'env', 'node_modules', '__pycache__', 'build', 'dist'}
            # 仅相对路径参与排除判断，祖先目录名不影响用户工程。
            import os
            for directory, dirs, files in os.walk(self.project_root):
                dirs[:] = [d for d in dirs if d not in ignored and not (Path(directory) / d).is_symlink()]
                for name in files:
                    path = Path(directory) / name
                    if not path.is_symlink():
                        try:
                            content = path.read_text(encoding='utf-8-sig')
                        except UnicodeDecodeError:
                            if path.suffix == '.py':
                                raise ValueError(f'Python 文件编码不受支持: {path}')
                            content = ''
                        sources[path.relative_to(self.project_root).as_posix()] = content
            old = self.read_graph()
            graph = build_graph(sources, old.model_dump(by_alias=True))
            if graph['diagnostics']:
                raise ValueError(f"图谱解析不完整: {graph['diagnostics']}")
            new = CodeGraph.model_validate(graph)
            return self._commit(old, new, ide_id, trigger_version or old.meta.version)

    def init_graph(self, ide_id):
        return self.sync(ide_id)

    def get_graph_diff(self, old_graph, new_graph):
        return GraphDiff(**detect_topology_changes(old_graph.model_dump(by_alias=True), new_graph.model_dump(by_alias=True)))

    def _commit(self, old, graph, ide_id, trigger_version):
        import json
        diff = self.get_graph_diff(old, graph)
        graph.meta.version = f'v{int(old.meta.version[1:]) + 1:04d}'
        graph.meta.last_updated = datetime.now(timezone.utc).isoformat()
        graph.meta.updated_by = ide_id
        graph.meta.total_nodes = len(graph.nodes)
        graph.meta.total_edges = len(graph.edges)
        entry = {'timestamp': graph.meta.last_updated, 'source_ai_ide': ide_id,
                 'action': 'init' if old.meta.version == 'v0000' else 'update',
                 'trigger_version': trigger_version, 'summary': '图谱扫描及增量更新', 'diff': diff.model_dump()}
        content = self.changelog_file.read_text(encoding='utf-8') if self.changelog_file.exists() else ''
        journal = {'graph': graph.model_dump(by_alias=True), 'changelog': content + json.dumps(entry, ensure_ascii=False) + '\n'}
        atomic_json(self.journal, journal)
        self._recover()
        return graph

    def update_graph(self, graph, ide_id, trigger_version):
        if not isinstance(trigger_version, str):
            raise ValueError('trigger_version 必须为字符串')
        with transaction(self.project_root, 'graph'):
            self._recover()
            return self._commit(self.read_graph(), graph.model_copy(deep=True), ide_id, trigger_version)
