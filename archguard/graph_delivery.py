"""只为派发生成图谱变化与去重上下文，不改动封存图谱。"""
import hashlib
import json


def graph_changes(report, paths):
    pool = {}

    def ref(value):
        if value is None:
            return None
        key = hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:16]
        if key in pool and pool[key] != value:
            raise ValueError('图谱内容标识冲突')
        pool[key] = value
        return key

    def compare(before, after):
        old, new = before.get('nodes', {}), after.get('nodes', {})
        changed = {p for p in set(old) | set(new) if old.get(p) != new.get(p)}
        def edge_map(graph):
            return {json.dumps(e, ensure_ascii=False, sort_keys=True): e for e in graph.get('edges', [])}
        oe, ne = edge_map(before), edge_map(after)
        added = [ne[k] for k in sorted(ne.keys() - oe.keys())]
        removed = [oe[k] for k in sorted(oe.keys() - ne.keys())]
        seeds = set(paths) | changed
        for edge in added + removed:
            seeds.update((edge.get('from'), edge.get('to')))
        seeds.discard(None)
        # 沿入边追溯所有上游；集合去重可终止循环依赖，不暗中截断。
        upstream = set(seeds)
        edges = {**oe, **ne}
        incoming = {}
        for edge in edges.values():
            incoming.setdefault(edge.get('to'), set()).add(edge.get('from'))
        pending = list(seeds)
        while pending:
            for parent in incoming.get(pending.pop(), ()):
                if parent is not None and parent not in upstream:
                    upstream.add(parent)
                    pending.append(parent)
        related = {k:e for k,e in edges.items() if e.get('to') in upstream or e.get('from') in seeds}
        included = upstream | {e.get(k) for e in related.values() for k in ('from','to')}
        changes, context = {}, {}
        for p in sorted(included - {None}):
            a, b = old.get(p), new.get(p)
            if a != b:
                changes[p] = {'operation':'add' if a is None else 'delete' if b is None else 'modify', 'before':ref(a), 'after':ref(b)}
            elif a is not None:
                context[p] = ref(a)
        return {'baseline_version':before.get('meta',{}).get('version'),
                'current_version':after.get('meta',{}).get('version'),
                'nodes_changed':changes, 'context_nodes':context,
                'edges_added':added, 'edges_removed':removed,
                'context_edges':[e for k,e in sorted(related.items()) if k in oe and k in ne]}

    physical = compare(report.graph_before, report.graph_after)
    declared = compare(report.declared_graph_before, report.declared_graph)
    return {'physical':physical, 'declared':declared, 'node_values':pool,
            'scope':'变化节点及其全部可达上游依赖、直接出依赖；节点前后值按内容去重；未建模关系不代表不存在'}
