"""纯函数图谱构建：输入固定版本源码，不写入任何文件。"""
from .source_text import decode_python
import ast
import hashlib
from pathlib import PurePosixPath


def build_graph(sources: dict[str, str], previous: dict | None = None, parse_cache: dict | None = None) -> dict:
    previous = previous or {}
    index = {}
    for path in sources:
        if path.endswith('.py'):
            module = path[:-3].replace('/', '.')
            if module.endswith('.__init__'):
                module = module[:-9]
            index[module] = path
    nodes, edges, diagnostics, coverage_warnings = {}, [], [], []
    for path in sorted(sources):
        old = previous.get('nodes', {}).get(path, {})
        nodes[path] = dict(old, module=old.get('module', PurePosixPath(path).parts[0] if '/' in path else 'root'),
                           purpose=old.get('purpose', '职责待补充'))
    # 非 Python 关系保留 A 的显式声明；不把未解析语言伪装成 AST 已验证。
    for edge in previous.get('edges', []):
        if edge.get('from') in sources and (not edge['from'].endswith('.py') or edge.get('type') != 'imports'):
            if edge.get('to') in sources or str(edge.get('to', '')).startswith('external:'):
                edges.append(edge)
    for module, path in sorted(index.items()):
        digest = hashlib.sha256(sources[path].encode()).hexdigest()
        cached = (parse_cache or {}).get(path)
        if cached is None or cached.get('hash') != digest:
            try:
                tree = ast.parse(sources[path], filename=path)
            except SyntaxError as exc:
                item = {'file': path, 'error': str(exc)}
                if previous.get('nodes', {}).get(path, {}).get('status') == 'non_active':
                    coverage_warnings.append(dict(item, reason='A 已声明非活跃历史节点，保留未验证语义'))
                    nodes[path]['parse_status'] = 'unparsed_non_active'
                    edges.extend(e for e in previous.get('edges', []) if e.get('from') == path and e.get('type') == 'imports' and (e.get('to') in sources or str(e.get('to','')).startswith('external:')))
                else:
                    diagnostics.append(item)
                continue
            specs = []
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    specs.append({'kind': 'import', 'names': [n.name for n in node.names]})
                elif isinstance(node, ast.ImportFrom):
                    specs.append({'kind': 'from', 'names': [n.name for n in node.names],
                                  'level': node.level, 'module': node.module or ''})
            cached = {'hash': digest, 'specs': specs, 'doc': ast.get_docstring(tree),
                      'exports': sorted(n.name for n in tree.body
                          if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)))}
            if parse_cache is not None:
                parse_cache[path] = cached
        old = dict(previous.get('nodes', {}).get(path, {}))
        old.pop('parse_status', None)
        imports = set()
        package = module if path.endswith('/__init__.py') else module.rpartition('.')[0]
        # 解析缓存只存语法事实；每次用完整节点索引重新解析目标，避免新增模块后边仍指向外部。
        for spec in cached['specs']:
            if spec['kind'] == 'import':
                imports.update(spec['names'])
            else:
                if spec['level']:
                    parts = package.split('.') if package else []
                    keep = len(parts) - spec['level'] + 1
                    if keep < 0:
                        diagnostics.append({'file': path, 'error': '相对导入超出包范围'})
                        continue
                    prefix = '.'.join(parts[:keep])
                    base = '.'.join(p for p in (prefix, spec['module']) if p)
                else:
                    base = spec['module']
                for name in spec['names']:
                    candidate = '.'.join(p for p in (base, name) if p)
                    imports.add(candidate if candidate in index else base)
        for imported in sorted(imports - {''}):
            target = index.get(imported)
            if target is None:
                # 顶层导入 package.child 也可能只对应项目中的包节点。
                prefix = imported
                while '.' in prefix and target is None:
                    prefix = prefix.rpartition('.')[0]
                    target = index.get(prefix)
            edges.append({'from': path, 'to': target or 'external:' + imported, 'type': 'imports'})
        nodes[path] = dict(old, module=old.get('module', PurePosixPath(path).parts[0] if '/' in path else 'root'),
                           purpose=old.get('purpose', cached['doc'] or '职责待补充'),
                           imports=sorted(imports), exports=cached['exports'])
    return {**previous, 'meta': {'version': 'v0000', 'last_updated': '', 'updated_by': 'scanner',
                     'total_nodes': len(nodes), 'total_edges': len(edges)},
            'modules': sorted({n['module'] for n in nodes.values()}), 'nodes': nodes, 'edges': edges,
            'diagnostics': diagnostics, 'coverage_warnings': coverage_warnings, 'supported_languages': ['python']}


def graph_at_commit(repo, commit_hash):
    if commit_hash is None:
        return build_graph({})
    commit = repo.commit(commit_hash)
    sources = {}
    diagnostics = []
    for item in commit.tree.traverse():
        if item.type == 'blob':
            try:
                sources[item.path] = decode_python(item.data_stream.read()) if item.path.endswith('.py') else ''
            except (UnicodeError, SyntaxError):
                sources[item.path] = ''
                if item.path.endswith('.py'):
                    diagnostics.append({'file': item.path, 'error': '源码编码无法确认，未解析'})
    graph = build_graph(sources)
    graph['diagnostics'].extend(diagnostics)
    graph['source_commit'] = commit.hexsha
    return graph
