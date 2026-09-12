"""验证用量日志不泄露正文、不干扰业务，并尊重授权。"""
import asyncio
import json
import pytest
from archguard import operation_log, phase_usage, project_control
from archguard.mcp.server import create_server


def test_authorization_and_redaction(tmp_path):
    app = create_server(tmp_path, 'dev')
    asyncio.run(app.call_tool('get_project_status', {}))
    assert not (tmp_path / '.ide_audit').exists()
    project_control.choose(tmp_path, 'project', True, confirmed=True)
    asyncio.run(app.call_tool('get_project_status', {}))
    rows = operation_log.read(tmp_path)['records']
    assert rows[0]['operation'] == 'get_project_status'
    assert rows[0]['response']['characters'] > 0
    assert rows[0]['actual_tokens'] is None
    from mcp.server.mcpserver.exceptions import ToolError
    with pytest.raises(ToolError):
        asyncio.run(app.call_tool('get_operation_usage_log', {'limit': 999}))
    assert operation_log.read(tmp_path)['records'][0]['status'] == 'failed'
    assert 'project-control' not in json.dumps(rows)


def test_pagination_and_log_failure(tmp_path, monkeypatch):
    for i in range(4):
        operation_log.write(tmp_path, str(i))
    page = operation_log.read(tmp_path, 2)
    other = operation_log.read(tmp_path, 2, page['next_before'])
    assert {r['operation'] for r in page['records'] + other['records']} == {'0','1','2','3'}
    def fail(*args):
        raise OSError('secret error content')
    monkeypatch.setattr(operation_log, 'atomic_json', fail)
    with pytest.warns(RuntimeWarning, match='OSError'):
        operation_log.write(tmp_path, 'committed')


def test_phase_unknown_and_idempotence(tmp_path, monkeypatch):
    project_control.choose(tmp_path, 'project', True, confirmed=True)
    monkeypatch.setattr(phase_usage, 'snapshot', lambda *a: {'status':'observed','source':'test','counts':{'totalTokens':100}})
    start = phase_usage.begin(tmp_path, 'A-thread', 'record_changes', 'A')
    first = phase_usage.finish(tmp_path, start['measurement_id'], 'A')
    assert first['this_phase_tokens'] is None
    phase_usage.finish(tmp_path, start['measurement_id'], 'A')
    records = operation_log.read(tmp_path)['records']
    assert len(records) == 1
    assert records[0]['settlement'] == 'unknown_or_pending'
    assert records[0]['thread_total_tokens'] == 100
