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
    analysis = data.get('graph_analysis', {})
    orphans = analysis.get('orphan_nodes', [])
    cycles = analysis.get('cycles_detected', [])
    analysis['global_context_counts'] = {'orphan_nodes':len(orphans), 'cycles_detected':len(cycles)}
    analysis['orphan_nodes'] = sorted(p for p in orphans if p in paths)
    analysis['cycles_detected'] = [cycle for cycle in cycles if set(cycle) & paths]
    analysis['context_scope'] = '孤立节点和环仅发送涉及本次文件的项；全局数量仅供背景，不作本次违规结论；完整列表封存在本地'
    data['delivery'] = {'graph_scope': 'changed_files_and_direct_dependencies',
                        'full_evidence': '本地已封存，缺证时请求指定文件，不能把局部视图当全局无风险证明'}
    text = json.dumps(data,ensure_ascii=False,separators=(',',':'))
    if len(text) > MAX_PACKET_CHARS:
        raise ValueError(f'审计证据包 {len(text)} 字符超过 {MAX_PACKET_CHARS} 字符预算；已停止模型派发，需缩小提交或分段审阅，不截断证据')
    return text


def prepared_summary(batch):
    return {'base_commit': batch['base_commit'], 'tree': batch['tree'],
            'prompt_count':len(batch['prompts']), 'ledger_event_count':len(batch['ledger_events']),
            'graph':graph_summary(batch['declared_graph']), 'sealed_locally':True, 'usage_measurement_count':len(batch.get('usage_measurement_ids', []))}


MAX_MESSAGE_CHARS = 24000


def message_parts(report, request_id=None):
    from pathlib import Path
    from archguard.adapters.codex.session_manager import VERDICT_SCHEMA
    instructions = (Path(__file__).parent/'templates/skill_codex_audit.md').read_text(encoding='utf-8')
    contract = '机器附录为裁决对象。' if request_id is None else '机器附录为 {"request_id":"' + request_id + '","verdict":<裁决对象>}。'
    schema = json.dumps(VERDICT_SCHEMA,ensure_ascii=False,separators=(',',':'))
    packet = audit_packet(report)
    parts = {'instructions':instructions, 'contract':contract, 'verdict_schema':schema, 'evidence':packet}
    total = sum(len(v) for v in parts.values()) + 100
    if total > MAX_MESSAGE_CHARS:
        raise ValueError(f'完整 B 消息 {total} 字符超过 {MAX_MESSAGE_CHARS} 预算；未派发，不截断证据')
    return parts


def build_message(report, request_id=None, include_instructions=True):
    p = message_parts(report,request_id)
    return ((p['instructions']+'\n') if include_instructions else '') + p['contract'] + '\n裁决 schema：\n' + p['verdict_schema'] + '\n固定提交事实包：\n' + p['evidence']


def payload_manifest(report):
    parts = message_parts(report, '0'*32)
    data = json.loads(parts['evidence'])
    return {'unit':'Unicode 字符（不是实际 token）', 'message_characters':len(build_message(report,'0'*32)),
            'limit':MAX_MESSAGE_CHARS,'sections':{k:len(v) for k,v in parts.items()},
            'evidence_fields':{k:len(json.dumps(v,ensure_ascii=False,separators=(',',':'))) for k,v in data.items()},
            'scope':'完整证据保留本地；载荷大小不含宿主历史、系统工具描述和模型输出'}
