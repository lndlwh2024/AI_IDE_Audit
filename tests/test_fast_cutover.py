import importlib.util
from pathlib import Path
import git
import pytest
from archguard.storage import atomic_json
from archguard.sync.graph import GraphManager
from archguard import project_control as control
from scripts.legacy_sync_assets import manifest


def load_switch(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).parents[1] / 'scripts'))
    spec = importlib.util.spec_from_file_location('external_switch', Path(__file__).parents[1] / 'scripts/switch_project.py')
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


def test_one_way_cutover_preserves_assets_waits_for_a_and_has_no_rollback(tmp_path, monkeypatch):
    module = load_switch(monkeypatch)
    git.Repo.init(tmp_path)
    source = tmp_path / '.ai-sync'
    (source / 'collab').mkdir(parents=True)
    (source / 'collab/ledger.jsonl').write_text('', encoding='utf-8')
    (source / 'collab/AUDIT_LOG.md').write_text('历史资产', encoding='utf-8')
    atomic_json(source / 'codegraph/graph.json', GraphManager(tmp_path).read_graph().model_dump(mode='json', by_alias=True))
    old = tmp_path / '.agents/skills/dual-agent-sync'
    old.mkdir(parents=True); (old / 'SKILL.md').write_text('旧入口', encoding='utf-8')
    before = manifest(source)
    assert module.switch(tmp_path)['status'] == 'planned'
    assert not (tmp_path / '.ide_audit').exists()
    class Client:
        def __enter__(self): return self
        def __exit__(self, *a): pass
    from archguard.adapters.codex.session_manager import CodexSessionManager
    monkeypatch.setattr(CodexSessionManager, '_project_id', lambda *a: 'p')
    monkeypatch.setattr(module, 'install_to_project', lambda root: None)
    original_init = CodexSessionManager.__init__
    monkeypatch.setattr(CodexSessionManager, '__init__', lambda self, root: original_init(self, root, client_factory=Client))
    result = module.switch(tmp_path, True, True)
    assert result['status'] == 'awaiting_a_validation'
    assert result['rollback'] is False
    assert manifest(source) == before
    assert not old.exists()
    assert (tmp_path / '.ide_audit/legacy-assets/disabled-skills/.agents/skills/dual-agent-sync/SKILL.md').read_text(encoding='utf-8') == '旧入口'
    assert control.status(tmp_path)['status'] == 'pending_a'
    with pytest.raises(PermissionError): module.finalize(tmp_path)
    assert module.switch(tmp_path, True, True)['status'] == 'awaiting_a_validation'
    assert not hasattr(module, 'rollback')
