"""覆盖 NEWS 一行文档验收暴露的派发、图谱和统计问题。"""
import hashlib
import json
import git
from click.testing import CliRunner
from archguard import phase_usage
from archguard.cli.main import cli
from archguard.sync.graph import GraphManager
from archguard.sync.workflow import SyncWorkflow
from archguard.adapters.git_hook import install_post_commit_hook,uninstall_post_commit_hook,hook_path
from archguard.storage import read_json,atomic_json,metadata_path
from tests.control_helpers import authorize
from tests.test_remaining_features import event
from tests.test_delivery_regressions import make_report


def test_notify_enqueues_before_output_failure(tmp_path,monkeypatch):
    import archguard.runtime as runtime
    import archguard.dispatch_queue as queue
    import click
    authorize(tmp_path)
    calls=[]
    monkeypatch.setattr(runtime,'audit_project',lambda *a:make_report())
    monkeypatch.setattr(queue,'enqueue',lambda *a:calls.append('queued') or {'status':'queued'})
    def broken(*a,**k):raise UnicodeEncodeError('gbk','🔔',0,1,'unsupported')
    monkeypatch.setattr(click,'echo',broken)
    result=CliRunner().invoke(cli,['--project-root',str(tmp_path),'audit','--notify'])
    assert result.exit_code!=0 and calls==['queued']


def test_document_operation_preserves_architecture_artifacts(tmp_path):
    (tmp_path/'main.py').write_text('def run(): pass\n',encoding='utf-8')
    graph=GraphManager(tmp_path);before=graph.sync('codex')
    files={p:p.read_bytes() for p in (graph.graph_file,graph.changelog_file,graph.graph_dir/'GRAPH_SUMMARY.md')}
    (tmp_path/'test.md').write_text('只验证插件。\n',encoding='utf-8')
    payload=event();payload['event_type']='doc_update';payload['scope']['files_changed']=[];payload['scope']['docs_changed']=['test.md']
    result=SyncWorkflow(tmp_path).complete('docs-only',payload)
    assert result['graph_version']==before.meta.version
    assert all(p.read_bytes()==value for p,value in files.items())
    assert 'test.md' not in graph.read_graph().nodes


def test_no_new_host_observation_is_not_zero_cost(tmp_path,monkeypatch):
    authorize(tmp_path)
    monkeypatch.setattr(phase_usage,'snapshot',lambda *a:{'source':'host','status':'observed','counts':{'totalTokens':120}})
    start=phase_usage.begin(tmp_path,'a','prepare_commit','A')
    result=phase_usage.finish(tmp_path,start['measurement_id'],'A')
    assert result['this_phase_tokens'] is None
    assert result['observed_interval_delta']==0
    assert result['settlement']=='no_new_observation'
    assert '本次 0 token' not in result['display']


def test_legacy_managed_hook_upgrade_keeps_original_chain(tmp_path):
    git.Repo.init(tmp_path);hook=hook_path(tmp_path)
    original=b'#!/bin/sh\necho prior\n';hook.write_bytes(original)
    install_post_commit_hook(tmp_path)
    hook.write_text(hook.read_text(encoding='utf-8').replace(' -X utf8 -m',' -m'),encoding='utf-8')
    path=metadata_path(tmp_path,'hook-install.json');manifest=read_json(path)
    atomic_json(path,dict(manifest,installed_hash=hashlib.sha256(hook.read_bytes()).hexdigest()))
    install_post_commit_hook(tmp_path)
    assert ' -X utf8 -m' in hook.read_text(encoding='utf-8')
    uninstall_post_commit_hook(tmp_path)
    assert hook.read_bytes()==original
