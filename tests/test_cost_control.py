"""验证编码、局部证据、阶段计数与分页交接。"""
import asyncio
import json
from pathlib import Path
import git
import pytest
from archguard.core.source_text import decode_python
from archguard.sync.graph import GraphManager
from archguard.storage import atomic_json, read_json, metadata_path
from archguard.delivery import audit_packet, graph_summary
from archguard import phase_usage
from tests.control_helpers import authorize
from tests.test_delivery_regressions import make_report


@pytest.mark.parametrize('encoding', ['utf-8-sig','utf-16','utf-32','gb18030'])
def test_python_encoding(encoding):
    text = '# coding: gb18030\nvalue="中文"\n' if encoding == 'gb18030' else 'value="中文"\n'
    assert '中文' in decode_python(text.encode(encoding))


def test_inactive_broken_source_is_visible_but_active_still_blocks(tmp_path):
    p=tmp_path/'old.py';p.write_text('def broken(',encoding='utf-16')
    manager=GraphManager(tmp_path)
    graph=manager.read_graph().model_dump(mode='json',by_alias=True)
    graph['nodes']={'old.py':{'module':'archive','purpose':'旧资料','status':'non_active'}}
    atomic_json(manager.graph_file,graph)
    updated=manager.sync('codex')
    assert updated.nodes['old.py'].parse_status == 'unparsed_non_active'
    assert updated.coverage_warnings[0]['file']=='old.py'
    (tmp_path/'active.py').write_text('def broken(',encoding='utf-8')
    with pytest.raises(ValueError):manager.sync('codex')


def test_audit_packet_keeps_all_diff_and_one_hop_without_entire_graph():
    report=make_report()
    report.changed_files=[{'path':'service.py','diff_content':'actual patch'}]
    report.graph_after={'nodes':{'service.py':{},'dependency.py':{},**{f'unrelated{i}.py':{} for i in range(5000)}},
                        'edges':[{'from':'service.py','to':'dependency.py','type':'imports'}]}
    report.graph_before = report.graph_after
    value=json.loads(audit_packet(report))
    assert set(value['information']['graph_changes']['physical']['context_nodes'])=={'service.py','dependency.py'}
    assert value['audit_one']['changed_files']==report.changed_files
    assert len(audit_packet(report)) < 3000
    report.prompts=[{'text':'x'*65000}]
    with pytest.raises(ValueError,match='预算'):audit_packet(report)


def test_phase_delta_is_idempotent_and_counter_reset_unknown(tmp_path,monkeypatch):
    authorize(tmp_path)
    samples=iter([{'source':'host','counts':{'totalTokens':100} ,'status':'observed'},
                  {'source':'host','counts':{'totalTokens':140},'status':'observed'},
                  {'source':'host','counts':{'totalTokens':140},'status':'observed'},
                  {'source':'host','counts':{'totalTokens':3},'status':'observed'}])
    monkeypatch.setattr(phase_usage,'snapshot',lambda *a:next(samples))
    identifier=phase_usage.begin(tmp_path,'a','before_edit','A')['measurement_id']
    first=phase_usage.finish(tmp_path,identifier,'A')
    assert first['this_phase_tokens']==40 and first['thread_total_tokens']==140
    assert phase_usage.finish(tmp_path,identifier,'A')==first
    identifier=phase_usage.begin(tmp_path,'a','after_commit','A')['measurement_id']
    assert phase_usage.finish(tmp_path,identifier,'A')['this_phase_tokens'] is None


def test_incremental_mcp_pages_do_not_return_full_graph(tmp_path):
    from archguard.sync.cursor import CursorManager
    from archguard.sync.ledger import LedgerManager
    from tests.test_remaining_features import event
    from archguard.mcp.server import create_server
    authorize(tmp_path)
    sid=CursorManager(tmp_path).start_session('codex')
    for _ in range(12):LedgerManager(tmp_path).append_event(event())
    app=create_server(tmp_path,'dev')
    async def call(name,args):
        result=await app.call_tool(name,args)
        assert not result.is_error, result
        content=result.content
        return json.loads(content[0].text)
    async def check():
        first=await call('get_sync_updates',{'ide_id':'codex','session_id':sid,'limit':2})
        assert len(first['events'])==2 and first['has_more']
        assert 'nodes' not in first['graph']
        await call('acknowledge_sync',{'ide_id':'codex','session_id':sid,'last_line':first['last_line']})
        second=await call('get_sync_updates',{'ide_id':'codex','session_id':sid,'limit':2})
        assert second['events'][0]['version']=='v0003'
    asyncio.run(check())


def test_generated_directories_skip_untracked_but_keep_tracked(tmp_path):
    repo=git.Repo.init(tmp_path)
    for directory in ('.pnpm-store','release-build-old','src'):
        (tmp_path/directory).mkdir()
        (tmp_path/directory/'x.py').write_text('value=1',encoding='utf-8')
    repo.index.add(['release-build-old/x.py'])
    graph=GraphManager(tmp_path).sync('codex')
    assert '.pnpm-store/x.py' not in graph.nodes
    assert 'release-build-old/x.py' in graph.nodes and 'src/x.py' in graph.nodes
    again=GraphManager(tmp_path).sync('codex')
    assert again.scan_stats['files_read']==0


def test_inactive_changed_file_remains_audit_diagnostic(tmp_path):
    from archguard.core.engine import run_audit
    repo=git.Repo.init(tmp_path)
    (tmp_path/'old.py').write_text('def broken(',encoding='utf-16')
    (tmp_path/'main.py').write_text('value=1',encoding='utf-8')
    repo.index.add(['old.py','main.py']);repo.index.commit('base')
    (tmp_path/'main.py').write_text('value=2',encoding='utf-8')
    repo.index.add(['main.py']);repo.index.commit('change main')
    snapshot={'prompts':[{'text':'update main'}], 'declared_graph':{'nodes':{'old.py':{'status':'non_active'}}}}
    result=run_audit(tmp_path,snapshot=snapshot)
    assert not any(d.get('file')=='old.py' for d in result.diagnostics)
    assert result.graph_after['coverage_warnings'][0]['file']=='old.py'
    (tmp_path/'old.py').write_text('def broken_again(',encoding='utf-16')
    repo.index.add(['old.py']);repo.index.commit('change old')
    result=run_audit(tmp_path,snapshot=snapshot)
    assert any(d.get('file')=='old.py' for d in result.diagnostics)
    assert result.analysis_status=='partial'


def test_phase_telemetry_failure_does_not_block_sync(tmp_path,monkeypatch):
    from archguard.adapters.codex.session_manager import CodexSessionManager
    authorize(tmp_path)
    def failed(*args,**kwargs):raise RuntimeError('thread not loaded')
    monkeypatch.setattr(CodexSessionManager,'__init__',lambda self,*a:None)
    monkeypatch.setattr(CodexSessionManager,'client_factory',failed,raising=False)
    result=phase_usage.snapshot(tmp_path,'a')
    assert result['status']=='unknown'
    assert result['counts']['totalTokens'] is None


def test_large_event_cannot_ack_until_all_chunks_read(tmp_path):
    from archguard.sync.cursor import CursorManager
    from archguard.sync.ledger import LedgerManager
    from tests.test_remaining_features import event
    from archguard.mcp.server import create_server
    authorize(tmp_path)
    value=event();value['summary']='x'*13000
    LedgerManager(tmp_path).append_event(value)
    sid=CursorManager(tmp_path).start_session('codex')
    app=create_server(tmp_path,'dev')
    async def check():
        args={'ide_id':'codex','session_id':sid}
        result=await app.call_tool('get_sync_event_chunk',args)
        first=json.loads(result.content[0].text)
        assert not first['complete'] and len(first['text'])==6000
        from mcp.server.mcpserver.exceptions import ToolError
        with pytest.raises(ToolError,match='不能跳过'):
            await app.call_tool('acknowledge_sync',dict(args,last_line=1))
        value=first
        while not value['complete']:
            result=await app.call_tool('get_sync_event_chunk',dict(args,offset=value['next_offset']))
            value=json.loads(result.content[0].text)
        result=await app.call_tool('acknowledge_sync',dict(args,last_line=1))
        assert not result.is_error
    asyncio.run(check())
