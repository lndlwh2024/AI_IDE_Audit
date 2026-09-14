"""故障恢复不得归档本轮需求；提交准备不得接受空证据。"""
import git,pytest
from archguard import project_control as control
from archguard.sync.prompts import record_prompt,get_pending_prompts
from archguard.runtime import prepare_commit
from tests.control_helpers import authorize


def test_failed_sync_retry_keeps_current_requirements(tmp_path,monkeypatch):
    monkeypatch.setattr(control,'verify_project',lambda root:None)
    git.Repo.init(tmp_path)
    authorize(tmp_path)
    record_prompt(tmp_path,'修复当前业务')
    original=get_pending_prompts(tmp_path)
    (tmp_path/'bad.py').write_text('def broken(')
    with pytest.raises(ValueError):control.refresh_a(tmp_path,'codex')
    (tmp_path/'bad.py').write_text('x=1')
    control.refresh_a(tmp_path,'codex')
    assert get_pending_prompts(tmp_path)==original


def test_prepare_rejects_empty_and_mismatched_ledger(tmp_path):
    from tests.evidence_helpers import prepare_evidence
    from archguard.sync.ledger import LedgerManager
    from tests.test_remaining_features import event
    repo=git.Repo.init(tmp_path)
    (tmp_path/'a.py').write_text('x=1')
    repo.index.add(['a.py'])
    with pytest.raises(ValueError,match='缺少'):prepare_commit(tmp_path)
    record_prompt(tmp_path,'新增文件')
    data=event();data['git']={'base_commit':'b'*40}
    LedgerManager(tmp_path).append_event(data)
    with pytest.raises(ValueError,match='账本'):prepare_commit(tmp_path)
    prepare_evidence(tmp_path)
    assert len(prepare_commit(tmp_path)['ledger_events'])==1
