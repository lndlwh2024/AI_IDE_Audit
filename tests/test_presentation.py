"""人读报告协议与历史机器回收兼容。"""
import json
import pytest
from archguard.presentation import parse_result, render, estimate
from archguard.storage import atomic_json, metadata_path
from tests.test_delivery_regressions import make_report, verdict


def test_machine_appendix_and_legacy():
    payload = verdict()
    assert parse_result(json.dumps(payload)) == payload
    assert parse_result('# 完整报告\n<details>\n```json\n' + json.dumps(payload) + '\n```\n</details>') == payload
    with pytest.raises(ValueError):
        parse_result('```json\n{}\n```\n```json\n{}\n```')


def test_report_sections_and_unknown_are_explicit(tmp_path):
    report = make_report()
    text = render(tmp_path, report, verdict())
    for section in ['审计一','审计二','最终审计结论','Token 预测与实际用量','整改与复核','无阶段记录']:
        assert section in text
    assert '本次实际 token' in text and '窗口累计 token' in text
    assert '100–500' in text
    assert not (tmp_path / '.ide_audit').exists()
    assert estimate('x'*100)['estimated_payload_tokens_low'] == 25


def test_only_bound_phase_and_current_audit_usage(tmp_path):
    report = make_report()
    for key, audit_id in [('a', report.audit_id),('b','other')]:
        atomic_json(metadata_path(tmp_path,'usage-phases',key+'.json'), {'id':key, 'audit_id':audit_id, 'phase':'dispatch','status':'completed','counts':{'totalTokens':123 if key=='a' else 999999},'after':{'counts':{'totalTokens':456}}})
    text = render(tmp_path, report, verdict())
    assert '| 123 | 456 |' in text
    assert '999999' not in text


def test_precommit_usage_binding_rejects_wrong_baseline(tmp_path):
    import git
    from archguard.runtime import prepare_commit, audit_project
    repo = git.Repo.init(tmp_path)
    actor = git.Actor('test','test@example.com')
    (tmp_path/'note.md').write_text('first')
    repo.index.add(['note.md'])
    base = repo.index.commit('base', author=actor, committer=actor).hexsha
    identifier = 'a'*32
    phase = {'id':identifier,'role':'A','base_commit':'wrong','phase':'before_edit','status':'completed'}
    path = metadata_path(tmp_path,'usage-phases',identifier+'.json')
    atomic_json(path,phase)
    with pytest.raises(ValueError,match='基线'):
        prepare_commit(tmp_path,[identifier])
    atomic_json(path,dict(phase,base_commit=base))
    (tmp_path/'note.md').write_text('second')
    repo.index.add(['note.md'])
    batch=prepare_commit(tmp_path,[identifier])
    assert batch['usage_measurement_ids']==[identifier]
    commit=repo.index.commit('next',author=actor,committer=actor).hexsha
    audit_project(tmp_path)
    from archguard.storage import read_json
    assert read_json(metadata_path(tmp_path,'jobs',commit,'input.json'))['usage_measurement_ids']==[identifier]


def test_window_total_survives_missing_phase(tmp_path):
    from archguard.phase_usage import window_path
    report=make_report()
    atomic_json(metadata_path(tmp_path,'usage-phases','a.json'), {'id':'a','audit_id':report.audit_id,'role':'A','thread_id':'A1','phase':'dispatch','status':'completed','counts':{'totalTokens':123}})
    atomic_json(window_path(tmp_path,'A1'), {'thread_id':'A1','observed_at':12345,'snapshot':{'counts':{'totalTokens':98765}}})
    text=render(tmp_path,report,verdict())
    assert '无阶段记录（不能据此认定未执行） | 98765 |' in text
    assert '| 123 | 98765 |' in text
    assert '12345' in text


def test_pending_and_shared_are_not_zero(tmp_path):
    report=make_report()
    atomic_json(metadata_path(tmp_path,'usage-phases','a.json'), {'id':'a','audit_id':report.audit_id,'role':'A','thread_id':'A1','phase':'before_edit','status':'completed','counts':{'totalTokens':0}})
    atomic_json(metadata_path(tmp_path,'operation-usage','1.json'), {'operation':'begin_edit','measurement_id':'a'})
    text=render(tmp_path,report,verdict())
    assert '待结算（无新增宿主观测）' in text
    assert '共享 before_edit 区间，非独占' in text


def test_mcp_prepare_automatically_binds_current_a(tmp_path, monkeypatch):
    import asyncio
    import git
    from archguard import phase_usage
    from archguard.mcp.server import create_server
    from tests.control_helpers import authorize
    from archguard.storage import read_json
    repo=git.Repo.init(tmp_path)
    actor=git.Actor('test','test@example.com')
    (tmp_path/'note.md').write_text('base')
    repo.index.add(['note.md'])
    repo.index.commit('base',author=actor,committer=actor)
    authorize(tmp_path,'project')
    monkeypatch.setattr(phase_usage,'snapshot',lambda *a:{'status':'observed','source':'test','counts':{'totalTokens':100}})
    app=create_server(tmp_path,'dev')
    async def run():
        result=await app.call_tool('begin_token_phase',{'thread_id':'A1','phase':'before_edit'})
        identifier=json.loads(result.content[0].text)['measurement_id']
        await app.call_tool('finish_token_phase',{'measurement_id':identifier})
        result=await app.call_tool('prepare_audit_commit',{})
        assert json.loads(result.content[0].text)['usage_measurement_count']==1
        assert read_json(metadata_path(tmp_path,'prepared.json'))['usage_measurement_ids']==[identifier]
    asyncio.run(run())
