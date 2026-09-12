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
    for section in ['审计一','审计二','最终审计结论','Token 预测与实际用量','整改与复核','未知/未绑定']:
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
