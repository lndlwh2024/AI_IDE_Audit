"""验证 A 接入顺序、图谱刷新失败门槛及租约续期。"""
import asyncio
import json
import os
import sys
from datetime import datetime, timezone, timedelta
import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from archguard.storage import read_json, atomic_json
from archguard.sync.lock import SyncLock, LockError
from archguard.adapters.codex.installer import install_to_project


def test_a_entry_refresh_and_failure_gate(tmp_path):
    import git
    from tests.control_helpers import authorize
    git.Repo.init(tmp_path)
    authorize(tmp_path, ready=False)
    source = tmp_path / 'service.py'
    source.write_text('value = 1', encoding='utf-8')
    async def check():
        params = StdioServerParameters(command=sys.executable, args=['-c', 'from archguard import project_control; project_control.verify_project=lambda root: None; from archguard.mcp.server import run_mcp_server; run_mcp_server()',
            '--project-root', str(tmp_path), '--role', 'dev'], env=dict(os.environ))
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as client:
                await client.initialize()
                result = await client.call_tool('start_sync_session', {'ide_id': 'codex'})
                assert not result.is_error
                session_id = result.content[0].text
                graph_file = tmp_path / '.ide_audit/codegraph/graph.json'
                assert 'service.py' in read_json(graph_file)['nodes']
                source.unlink()
                (tmp_path / 'new.py').write_text('import os', encoding='utf-8')
                result = await client.call_tool('enter_sync_session', {'ide_id': 'codex', 'session_id': session_id})
                assert not result.is_error
                assert 'service.py' not in read_json(graph_file)['nodes']
                assert 'new.py' in read_json(graph_file)['nodes']
                original = graph_file.read_bytes()
                (tmp_path / 'new.py').write_text('def broken(', encoding='utf-8')
                result = await client.call_tool('enter_sync_session', {'ide_id': 'codex', 'session_id': session_id})
                assert result.is_error
                assert graph_file.read_bytes() == original
                result = await client.call_tool('begin_edit', {'ide_id': 'codex', 'session_id': session_id,
                    'files': ['new.py'], 'purpose': '测试'})
                assert result.is_error
    asyncio.run(check())


def test_renewal_preserves_owner_and_rejects_expired_lease(tmp_path):
    owner = SyncLock(tmp_path)
    owner.acquire_intent_lock('service.py', 'codex', '测试')
    path = owner._scope_path('service.py')
    original = read_json(path)
    owner.renew_intent_locks(['service.py'])
    renewed = read_json(path)
    assert renewed['lock_id'] == original['lock_id']
    assert renewed['expires_at'] >= original['expires_at']
    with pytest.raises(LockError):
        SyncLock(tmp_path).renew_intent_locks(['service.py'])
    expired = dict(renewed, expires_at=(datetime.now(timezone.utc)-timedelta(seconds=1)).isoformat())
    atomic_json(path, expired)
    with pytest.raises(LockError):
        owner.renew_intent_locks(['service.py'])
    assert read_json(path) == expired


def test_plugin_install_does_not_read_legacy_business_assets(tmp_path):
    import git
    git.Repo.init(tmp_path)
    legacy = tmp_path / '.ai-sync'
    legacy.mkdir()
    path = legacy / 'ledger.jsonl'
    path.write_text('旧业务内容不是插件安装的校验输入', encoding='utf-8')
    from tests.control_helpers import authorize
    authorize(tmp_path, ready=False)
    install_to_project(tmp_path)
    assert path.read_text(encoding='utf-8') == '旧业务内容不是插件安装的校验输入'
    assert not (tmp_path / '.ide_audit/migrations').exists()
