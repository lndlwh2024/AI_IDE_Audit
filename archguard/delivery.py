"""控制模型接收的证据体积；完整封存数据始终保留在本地。"""
import json

MAX_PACKET_CHARS = 64000


def graph_summary(graph):
    return {'meta': graph.get('meta', {}), 'nodes_count': len(graph.get('nodes', {})),
            'edges_count': len(graph.get('edges', [])), 'scan_stats':graph.get('scan_stats', {}), 'coverage_warning_count':len(graph.get('coverage_warnings', [])), 'coverage_warnings':graph.get('coverage_warnings', [])[:10], 'detail_policy': '按文件读取，默认不发送全图'}


def graph_slice(graph, paths):
    seeds = set(paths)
    edges = [e for e in graph.get('edges', []) if e.get('from') in seeds or e.get('to') in seeds]
    included = seeds | {e.get(k) for e in edges for k in ('from', 'to')}
    return dict(graph_summary(graph), nodes={p: n for p,n in graph.get('nodes', {}).items() if p in included},
                edges=edges, scope='本次文件及一跳入出依赖；完整图谱保留本地')


def audit_packet(report):
    data = report.model_dump(mode='json')
    paths = {f['path'] for f in data['changed_files']} | {f['rename_from'] for f in data['changed_files'] if f.get('rename_from')}
    for key in ('graph_before','graph_after','declared_graph','declared_graph_before'):
        data[key] = graph_slice(data.get(key, {}), paths)
    data['delivery'] = {'graph_scope': 'changed_files_and_direct_dependencies',
                        'full_evidence': '本地已封存，缺证时请求指定文件，不能把局部视图当全局无风险证明'}
    text = json.dumps(data,ensure_ascii=False,separators=(',',':'))
    if len(text) > MAX_PACKET_CHARS:
        raise ValueError(f'审计证据包 {len(text)} 字符超过 {MAX_PACKET_CHARS} 字符预算；已停止模型派发，需缩小提交或分段审阅，不截断证据')
    return text


def prepared_summary(batch):
    return {'base_commit': batch['base_commit'], 'tree': batch['tree'],
            'prompt_count':len(batch['prompts']), 'ledger_event_count':len(batch['ledger_events']),
            'graph':graph_summary(batch['declared_graph']), 'sealed_locally':True}
