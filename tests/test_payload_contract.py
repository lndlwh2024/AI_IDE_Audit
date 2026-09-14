"""按真实体积缺陷验证载荷、报告交付与 B 用量不串轮。"""
import json
from copy import deepcopy
import pytest
from tests.test_delivery_regressions import make_report, verdict
from archguard.delivery import audit_packet, build_message, payload_manifest
from archguard.presentation import delivery_status
from archguard.storage import atomic_json, metadata_path


def test_global_orphans_not_repeated_in_small_commit():
    report=make_report()
    path=report.changed_files[0]['path']
    report.graph_analysis={'orphan_nodes':[path]+[f'unrelated/{i}.py' for i in range(1000)], 'cycles_detected':[['unrelated/1.py','unrelated/2.py'],[path,'dep.py']], 'nodes_added':[path]}
    before=deepcopy(report.graph_analysis)
    packet=json.loads(audit_packet(report))
    assert packet['audit_one']['graph_checks']['orphan_nodes']==[path]
    assert packet['audit_one']['graph_checks']['global_context_counts']['orphan_nodes']==1001
    assert packet['audit_one']['graph_checks']['cycles_detected']==[[path,'dep.py']]
    assert report.graph_analysis==before
    assert 'unrelated/999.py' not in build_message(report)
    assert payload_manifest(report)['message_characters']<10000


def test_complete_message_budget_includes_instructions():
    report=make_report()
    report.prompts=[{'text':'x'*23500}]
    assert len(audit_packet(report))<64000
    with pytest.raises(ValueError,match='完整 B 消息'):
        build_message(report)


def test_raw_verdict_is_not_report_delivery(tmp_path):
    report=make_report()
    atomic_json(metadata_path(tmp_path,'jobs',report.audit_id,'dispatch.json'),{'status':'completed','thread_id':'B'})
    state=delivery_status(tmp_path,report.audit_id)
    assert state['audit_status']=='completed'
    assert state['report_delivery_status']=='report_not_ready'
    assert not state['chat_report_present']


def test_b_usage_never_reuses_previous_audit(tmp_path,monkeypatch):
    from archguard import usage,phase_usage
    atomic_json(metadata_path(tmp_path,'session.json'),{'thread_id':'B'})
    monkeypatch.setattr(usage,'refresh_current',lambda root:{'threads':[{'thread_id':'B','turns':{'old':{'audit_id':'old','counts':{'totalTokens':999}}},'latest':{'counts':{'totalTokens':1000}}}], 'observed_total_tokens':1000})
    result=phase_usage.compact_b(tmp_path,'new')
    assert result['this_turn_tokens'] is None
    assert result['thread_total_tokens']==1000


def test_deleted_module_keeps_transitive_upstream_and_preimage():
    report = make_report()
    report.changed_files = [{'path':'module.py','change_type':'D','diff_content':'-delete'}]
    report.graph_before = {'nodes':{'module.py':{'purpose':'删除前职责'},'service.py':{'purpose':'服务'},'entry.py':{'purpose':'入口'},'unrelated.py':{}},
        'edges':[{'from':'entry.py','to':'service.py','type':'imports'},{'from':'service.py','to':'module.py','type':'imports'}]}
    report.graph_after = {'nodes':{k:v for k,v in report.graph_before['nodes'].items() if k!='module.py'},
        'edges':[report.graph_before['edges'][0]]}
    original = report.model_dump()
    data = json.loads(audit_packet(report))
    graph = data['information']['graph_changes']
    delta = graph['physical']
    assert delta['nodes_changed']['module.py']['operation']=='delete'
    assert graph['node_values'][delta['nodes_changed']['module.py']['before']]['purpose']=='删除前职责'
    assert set(delta['context_nodes'])=={'entry.py','service.py'}
    assert delta['edges_removed']==[report.graph_before['edges'][1]]
    assert data['audit_one']['changed_files']==report.changed_files
    assert 'graph_before' not in data and 'changed_files' not in data['information']
    assert report.model_dump()==original


def test_attribute_change_cycle_and_ledger_preserved():
    report = make_report()
    report.changed_files = [{'path':'a.py','diff_content':'patch'}]
    edges=[{'from':'a.py','to':'b.py'},{'from':'b.py','to':'a.py'}]
    report.graph_before={'nodes':{'a.py':{'exports':['old']},'b.py':{'purpose':'parent'}},'edges':edges}
    report.graph_after={'nodes':{'a.py':{'exports':['new']},'b.py':{'purpose':'parent'}},'edges':edges}
    report.declared_graph_before=deepcopy(report.graph_before)
    report.declared_graph=deepcopy(report.graph_after)
    report.ledger_events=[{'version':'v0001','context':{'original':'不改写原始记录'},'scope':{'files_changed':[]}}]
    info=json.loads(audit_packet(report))['information']
    graph=info['graph_changes']
    assert graph['physical']['nodes_changed']['a.py']['operation']=='modify'
    assert len(graph['node_values'])==3
    assert graph['physical']==graph['declared']
    assert info['ledger_events']==report.ledger_events


def test_manifest_accounts_for_entire_message_without_fake_actual_tokens():
    manifest=payload_manifest(make_report())
    rows=[r for g in manifest['categories'] for r in g['items']]
    assert sum(r['characters'] for r in rows)==manifest['message_characters']
    assert all(r['actual_tokens'] is None for r in rows)
    assert abs(sum(g['subtotal']['estimated_share_percent'] for g in manifest['categories'])-100)<0.03
    assert manifest['total']['estimated_share_percent']==100
