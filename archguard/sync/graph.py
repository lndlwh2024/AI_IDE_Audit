"""维护工作态图谱；先落可恢复记录，再原子提交图谱与变更日志。"""
import hashlib
from datetime import datetime, timezone
from pathlib import Path
from archguard.core.codegraph import build_graph
from archguard.core.source_text import decode_python
from archguard.core.graph_analyzer import detect_topology_changes
from archguard.storage import metadata_path, atomic_json, atomic_text, read_json, transaction
from .schemas import CodeGraph, GraphMeta, GraphDiff


class GraphManager:
    def __init__(self, project_root):
        self.project_root = Path(project_root).resolve()
        self.graph_file = metadata_path(project_root, 'codegraph', 'graph.json')
        self.graph_dir = self.graph_file.parent
        self.changelog_file = self.graph_dir / 'graph.changelog.jsonl'
        self.cache_file = self.graph_dir / 'scan-cache.json'
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
            value = journal['graph']
            summary = '# 架构图谱 · ' + value['meta']['version'] + '\n\n'
            summary += f"节点 {len(value['nodes'])}，依赖边 {len(value['edges'])}。\n\n"
            summary += '\n'.join('- ' + name + '：' + node.get('purpose', '职责待补充')
                                 for name, node in sorted(value['nodes'].items())) + '\n'
            atomic_text(self.graph_dir / 'GRAPH_SUMMARY.md', summary)
            if 'cache' in journal:
                atomic_json(self.cache_file, journal['cache'])
            self.journal.unlink()

    def preview(self, force=False):
        """只计算候选图谱和缓存，由调用者在事务中固定后发布。"""
        sources = {}
        old = self.read_graph()
        previous_cache = {} if force else read_json(self.cache_file, {})
        cache = {'files': {}, 'parsed': dict(previous_cache.get('parsed', {}))}
        files_read = 0
        ignored = {'.git', '.ide_audit', '.ai-sync', '.pytest_cache', '.venv', 'venv', 'env', 'node_modules', '__pycache__', 'build', 'dist'}
        # 已跟踪文件不因通用构建目录名称而丢失；插件元数据始终排除。
        tracked = set()
        try:
            import git
            repo = git.Repo(self.project_root)
            tracked = set(repo.git.ls_files(z=True).split('\0')) - {''}
        except (git.InvalidGitRepositoryError, git.NoSuchPathError):
            pass
        tracked_dirs = {str(parent).replace('\\', '/') for name in tracked for parent in Path(name).parents}
        artifacts = {'.pnpm-store', '.next', '.nuxt', '.mypy_cache', '.ruff_cache', '.tox'}
        def excluded(directory, name):
            relative = (Path(directory) / name).relative_to(self.project_root).as_posix()
            if name in {'.git', '.ide_audit', '.ai-sync'}:
                return True
            return relative not in tracked_dirs and (name in ignored or name in artifacts or name.startswith(('.tmp-', 'release-build-')))
        # 仅相对路径参与排除判断，祖先目录名不影响用户工程。
        import os
        for directory, dirs, files in os.walk(self.project_root):
            dirs[:] = [d for d in dirs if not excluded(directory, d) and not (Path(directory) / d).is_symlink()]
            for name in files:
                path = Path(directory) / name
                if not path.is_symlink():
                    relative = path.relative_to(self.project_root).as_posix()
                    stat = path.stat()
                    signature = [stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns]
                    prior = previous_cache.get('files', {}).get(relative, {})
                    if prior.get('stat') == signature:
                        content = prior['content']
                    else:
                        files_read += 1
                        try:
                            content = decode_python(path.read_bytes()) if path.suffix == '.py' else ''
                        except (UnicodeError, SyntaxError):
                            raise ValueError(f'Python 文件编码不受支持: {path}')
                        after = path.stat()
                        if signature != [after.st_size, after.st_mtime_ns, after.st_ctime_ns]:
                            raise ValueError(f'扫描期间文件发生变化，请重试: {relative}')
                    sources[relative] = content
                    cache['files'][relative] = {'stat': signature, 'content': content}
        cache['parsed'] = {k: v for k, v in cache['parsed'].items() if k in sources}
        # 新增普通说明文档不自动提升为架构节点；既有显式语义声明仍保留。
        sources = {p:c for p,c in sources.items() if p in old.nodes or Path(p).suffix.lower() not in {'.md', '.rst', '.txt'}}
        graph = build_graph(sources, old.model_dump(by_alias=True), cache['parsed'])
        graph['scan_stats'] = {'files_read': files_read, 'files_total': len(sources)}
        if graph['diagnostics']:
            raise ValueError(f"图谱解析不完整: {graph['diagnostics']}")
        new = CodeGraph.model_validate(graph)
        return old, new, cache

    def sync(self, ide_id, trigger_version=None, force=False):
        with transaction(self.project_root, 'graph'):
            self._recover()
            old, new, cache = self.preview(force)
            return self._commit(old, new, ide_id, trigger_version or old.meta.version, cache)

    def init_graph(self, ide_id):
        return self.sync(ide_id)

    def get_graph_diff(self, old_graph, new_graph):
        return GraphDiff(**detect_topology_changes(old_graph.model_dump(by_alias=True), new_graph.model_dump(by_alias=True)))

    def _commit(self, old, graph, ide_id, trigger_version, cache=None):
        import json
        def semantic(value):
            return {k:v for k,v in value.model_dump(by_alias=True).items() if k not in ('meta','scan_stats')}
        if old.meta.version != 'v0000' and semantic(old) == semantic(graph):
            if cache is not None:
                atomic_json(self.cache_file, cache)
            return old.model_copy(update={'scan_stats':getattr(graph, 'scan_stats', {})})
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
        if cache is not None:
            journal['cache'] = cache
        atomic_json(self.journal, journal)
        self._recover()
        return graph

    def update_graph(self, graph, ide_id, trigger_version):
        if not isinstance(trigger_version, str):
            raise ValueError('trigger_version 必须为字符串')
        with transaction(self.project_root, 'graph'):
            self._recover()
            return self._commit(self.read_graph(), graph.model_copy(deep=True), ide_id, trigger_version)

    def patch(self, ide_id, trigger_version, expected_version, nodes_upsert, nodes_remove, edges_add, edges_remove):
        """A 只提交变动；程序在锁内合并，版本不一致时拒绝覆盖。"""
        from .ledger import LedgerManager
        from .schemas import GraphEdge
        from archguard.core.ledger_analyzer import normalize
        if trigger_version not in {e.version for e in LedgerManager(self.project_root).read_all_events()}:
            raise ValueError('图谱变动必须关联真实账本版本')
        with transaction(self.project_root, 'graph'):
            self._recover()
            old = self.read_graph()
            if old.meta.version != expected_version:
                raise ValueError('图谱版本已变化，请重新读取相关节点后提交局部修改')
            if set(nodes_upsert) & set(nodes_remove):
                raise ValueError('不能同时更新和删除同一节点')
            data = old.model_dump(by_alias=True)
            for path in nodes_remove:
                normalize(path)
                if path not in data['nodes']:
                    raise ValueError('待删除节点不存在: ' + path)
                del data['nodes'][path]
            for path, fields in nodes_upsert.items():
                normalize(path)
                target = (self.project_root / path).resolve()
                if not target.is_relative_to(self.project_root) or not target.is_file():
                    raise ValueError('图谱声明包含不存在的项目文件: ' + path)
                if not isinstance(fields, dict):
                    raise ValueError('节点更新必须为字段对象')
                data['nodes'][path] = dict(data['nodes'].get(path, {}), **fields)
            def key(edge):
                return (edge['from'], edge['to'], edge['type'])
            edges = {key(e):e for e in data['edges']}
            for item in edges_remove:
                edge = GraphEdge.model_validate(item).model_dump(by_alias=True)
                if key(edge) not in edges:
                    raise ValueError('待删除依赖不存在')
                del edges[key(edge)]
            # 删除节点同时删除其关联边，不留下悬空引用。
            edges = {k:e for k,e in edges.items() if e['from'] not in nodes_remove and e['to'] not in nodes_remove}
            for item in edges_add:
                edge = GraphEdge.model_validate(item).model_dump(by_alias=True)
                edges[key(edge)] = edge
            for edge in edges.values():
                if edge['from'] not in data['nodes'] or (edge['to'] not in data['nodes'] and not edge['to'].startswith('external:')):
                    raise ValueError('图谱依赖引用不存在的节点')
            data['edges'] = list(edges.values())
            candidate = CodeGraph.model_validate(data)
            candidate.modules = sorted({n.module for n in candidate.nodes.values()})
            return self._commit(old, candidate, ide_id, trigger_version)
