"""通过官方 STDIO 客户端验证握手、角色工具集合和错误结果。"""
import asyncio
import os
import sys
from pathlib import Path
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


def test_stdio_audit_role_cannot_write(tmp_path):
    async def check():
        params = StdioServerParameters(command=sys.executable, args=['-m', 'archguard.mcp.server',
            '--project-root', str(tmp_path), '--role', 'audit'], env=dict(os.environ))
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                tools = (await session.list_tools()).tools
                assert {t.name for t in tools} == {'audit_changes', 'get_architecture_graph', 'get_ledger_records', 'get_file_diff', 'get_prompts'}
                assert all(t.input_schema is not None for t in tools)
                result = await session.call_tool('record_prompt', {'prompt_text': '不允许'})
                assert result.is_error
                result = await session.call_tool('audit_changes', {})
                assert result.is_error
        assert not (tmp_path / '.ide_audit').exists()
    asyncio.run(check())


def test_stdio_dev_records_prompt(tmp_path):
    async def check():
        params = StdioServerParameters(command=sys.executable, args=['-m', 'archguard.mcp.server',
            '--project-root', str(tmp_path), '--role', 'dev'], env=dict(os.environ))
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                names = {t.name for t in (await session.list_tools()).tools}
                assert {'record_prompt', 'record_sync_event', 'sync_graph', 'get_sync_updates', 'acknowledge_sync', 'prepare_audit_commit'} <= names
                result = await session.call_tool('record_prompt', {'prompt_text': '保留需求原文'})
                assert not result.is_error
        from archguard.sync.prompts import get_pending_prompts
        assert get_pending_prompts(tmp_path)[0]['text'] == '保留需求原文'
    asyncio.run(check())
