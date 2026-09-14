"""接管读取策略与局部语义更新的回归验证。"""
from uuid import uuid4
import pytest
from archguard.sync.cursor import CursorManager
from archguard.sync.ledger import LedgerManager
from archguard.sync.graph import GraphManager
from tests.test_remaining_features import event


def test_new_task_last_two_reconnect_continues_and_unknown_never_full(tmp_path):
    ledger=LedgerManager(tmp_path)
    for _ in range(6): ledger.append_event(event())
    manager=CursorManager(tmp_path)
    task=str(uuid4())
    sid=manager.start_session('codex',task)
    rows,total=manager.get_unread_events('codex',sid)
    assert [e.version for e in rows]==['v0005','v0006']
    manager.update_cursor('codex',sid,'v0006',6)
    for _ in range(3): ledger.append_event(event())
    reconnected=CursorManager(tmp_path)
    assert reconnected.start_session('codex',task)==sid
    assert [e.version for e in reconnected.get_unread_events('codex',sid)[0]]==['v0007','v0008','v0009']
    new=reconnected.start_session('codex',str(uuid4()))
    assert [e.version for e in reconnected.get_unread_events('codex',new)[0]]==['v0008','v0009']
    assert [e.version for e in reconnected.get_unread_events('codex','unknown')[0]]==['v0008','v0009']
    reconnected.update_cursor('codex',new,'v0009',9)
    assert reconnected.get_unread_events('codex',new)[0]==[]


def test_patch_preserves_other_nodes_checks_version_and_removes_edges(tmp_path):
    (tmp_path/'a.py').write_text('import b\n',encoding='utf-8')
    (tmp_path/'b.py').write_text('x=1\n',encoding='utf-8')
    graph=GraphManager(tmp_path)
    old=graph.sync('codex')
    ledger=LedgerManager(tmp_path).append_event(event())
    new=graph.patch('codex',ledger.version,old.meta.version,{'a.py':{'purpose':'新的职责'}},[],[],[])
    assert new.nodes['a.py'].purpose=='新的职责'
    assert new.nodes['b.py']==old.nodes['b.py']
    assert new.edges==old.edges
    with pytest.raises(ValueError,match='版本已变化'):
        graph.patch('codex',ledger.version,old.meta.version,{'a.py':{'purpose':'覆盖'}},[],[],[])
    assert graph.read_graph()==new
    with pytest.raises(ValueError,match='不存在的节点'):
        graph.patch('codex',ledger.version,new.meta.version,{},[],[{'from':'a.py','to':'missing.py','type':'imports'}],[])
    assert graph.read_graph()==new
    deleted=graph.patch('codex',ledger.version,new.meta.version,{},['b.py'],[],[])
    assert 'b.py' not in deleted.nodes and not deleted.edges


def test_latest_two_handles_short_and_empty_ledgers(tmp_path):
    manager=CursorManager(tmp_path)
    assert manager.get_unread_events('codex',manager.start_session('codex'))[0]==[]
    LedgerManager(tmp_path).append_event(event())
    assert len(manager.get_unread_events('codex',manager.start_session('codex'))[0])==1


def test_mcp_working_graph_and_patch_are_dev_only(tmp_path):
    import asyncio,json
    from tests.control_helpers import authorize
    from archguard.mcp.server import create_server
    authorize(tmp_path)
    (tmp_path/'a.py').write_text('x=1\n',encoding='utf-8')
    original=GraphManager(tmp_path).sync('codex')
    version=LedgerManager(tmp_path).append_event(event()).version
    async def check():
        dev=create_server(tmp_path,'dev')
        read=await dev.call_tool('get_working_graph',{'file_paths':['a.py']})
        assert not read.is_error
        data=json.loads(read.content[0].text)
        assert data['meta']['version']==original.meta.version
        result=await dev.call_tool('patch_architecture_graph',{'ide_id':'codex','trigger_version':version,
            'expected_version':data['meta']['version'],'nodes_upsert':{'a.py':{'purpose':'只更新这一处'}}})
        assert not result.is_error,result
        assert GraphManager(tmp_path).read_graph().nodes['a.py'].purpose=='只更新这一处'
        audit=create_server(tmp_path,'audit')
        from mcp.server.mcpserver.exceptions import ToolError
        with pytest.raises(ToolError, match='Unknown tool'):
            await audit.call_tool('patch_architecture_graph',{})
    asyncio.run(check())
