"""升级后旧 MCP 拒绝写入，版本探测本身不改业务数据。"""
import asyncio
import json
import pytest
from archguard import runtime_version
from archguard.mcp.server import create_server
from mcp.server.mcpserver.exceptions import ToolError


def test_running_version_is_reported_before_work(tmp_path):
    result=asyncio.run(create_server(tmp_path,'dev').call_tool('get_project_status',{}))
    state=json.loads(result.content[0].text)
    assert state['runtime']['running_version']==runtime_version.__version__
    assert not state['runtime']['restart_required']
    assert not (tmp_path/'.ide_audit').exists()


def test_stale_service_refuses_operations(tmp_path, monkeypatch):
    monkeypatch.setattr(runtime_version,'installed_version',lambda:'new-version')
    app=create_server(tmp_path,'dev')
    state=json.loads(asyncio.run(app.call_tool('get_project_status',{})).content[0].text)
    assert state['runtime']['restart_required']
    with pytest.raises(ToolError,match='仍运行旧版本'):
        asyncio.run(app.call_tool('prepare_audit_commit',{}))
    assert not (tmp_path/'.ide_audit/prepared.json').exists()
