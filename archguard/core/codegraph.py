"""纯函数图谱构建：输入固定版本源码，不写入任何文件。"""
import ast
from pathlib import PurePosixPath


def build_graph(sources: dict[str, str], previous: dict | None = None) -> dict:
    previous = previous or {}
    index = {}
    for path in sources:
        if path.endswith('.py'):
            module = path[:-3].replace('/', '.')
            if module.endswith('.__init__'):
                module = module[:-9]
            index[module] = path
    nodes, edges, diagnostics = {}, [], []
    for path in sorted(sources):
        old = previous.get('nodes', {}).get(path, {})
        nodes[path] = dict(old, module=old.get('module', PurePosixPath(path).parts[0] if '/' in path else 'root'),
                           purpose=old.get('purpose', '职责待补充'))
    # 非 Python 关系保留 A 的显式声明；不把未解析语言伪装成 AST 已验证。
    for edge in previous.get('edges', []):
        if edge.get('from') in sources and not edge['from'].endswith('.py'):
            if edge.get('to') in sources or str(edge.get('to', '')).startswith('external:'):
                edges.append(edge)
    for module, path in sorted(index.items()):
        try:
            tree = ast.parse(sources[path], filename=path)
        except SyntaxError as exc:
            diagnostics.append({'file': path, 'error': str(exc)})
            continue
        old = previous.get('nodes', {}).get(path, {})
        imports = set()
        package = module if path.endswith('/__init__.py') else module.rpartition('.')[0]
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.update(item.name for item in node.names)
            elif isinstance(node, ast.ImportFrom):
                if node.level:
                    parts = package.split('.') if package else []
                    keep = len(parts) - node.level + 1
                    if keep < 0:
                        diagnostics.append({'file': path, 'error': '相对导入超出包范围'})
                        continue
                    prefix = '.'.join(parts[:keep])
                    base = '.'.join(p for p in (prefix, node.module) if p)
                else:
                    base = node.module or ''
                for item in node.names:
                    candidate = '.'.join(p for p in (base, item.name) if p)
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
                           purpose=old.get('purpose', ast.get_docstring(tree) or '职责待补充'),
                           imports=sorted(imports), exports=sorted(n.name for n in tree.body
                              if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))))
    return {'meta': {'version': 'v0000', 'last_updated': '', 'updated_by': 'scanner',
                     'total_nodes': len(nodes), 'total_edges': len(edges)},
            'modules': sorted({n['module'] for n in nodes.values()}), 'nodes': nodes, 'edges': edges,
            'diagnostics': diagnostics, 'supported_languages': ['python']}


def graph_at_commit(repo, commit_hash):
    if commit_hash is None:
        return build_graph({})
    commit = repo.commit(commit_hash)
    sources = {}
    diagnostics = []
    for item in commit.tree.traverse():
        if item.type == 'blob':
            try:
                sources[item.path] = item.data_stream.read().decode('utf-8-sig')
            except UnicodeDecodeError:
                sources[item.path] = ''
                if item.path.endswith('.py'):
                    diagnostics.append({'file': item.path, 'error': '源码不是 UTF-8，未解析'})
    graph = build_graph(sources)
    graph['diagnostics'].extend(diagnostics)
    graph['source_commit'] = commit.hexsha
    return graph
