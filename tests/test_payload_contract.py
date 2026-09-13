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
    assert packet['graph_analysis']['orphan_nodes']==[path]
    assert packet['graph_analysis']['global_context_counts']['orphan_nodes']==1001
    assert packet['graph_analysis']['cycles_detected']==[[path,'dep.py']]
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
