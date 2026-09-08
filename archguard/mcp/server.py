"""官方 MCP STDIO 服务。角色和工程路径在启动时绑定，不接受调用者升级权限。"""
import argparse
from pathlib import Path
from mcp.server.mcpserver import MCPServer
from archguard.runtime import get_result, prepare_commit


def create_server(project_root, role='audit', audit_id=None):
    if role not in ('dev', 'audit'):
        raise ValueError('未知服务角色')
    root = str(Path(project_root).resolve())
    app = MCPServer('ide-audit-' + role)
    bound_id = audit_id

    def view():
        nonlocal bound_id
        result = get_result(root, bound_id)
        # 首次绑定后始终使用相同任务，避免用户追问过程中 HEAD 变化。
        bound_id = result.audit_id
        return result

    @app.tool(description='读取绑定提交的客观事实包，不重新执行或写入审计')
    def audit_changes() -> dict:
        return view().model_dump(mode='json')

    @app.tool(description='读取绑定提交的代码图谱快照')
    def get_architecture_graph() -> dict:
        result = view()
        return {'physical_before': result.graph_before, 'physical_after': result.graph_after,
                'declared_before': result.declared_graph_before, 'declared_after': result.declared_graph}

    @app.tool(description='读取绑定提交的全部申报事件')
    def get_ledger_records() -> list[dict]:
        return view().ledger_events

    @app.tool(description='读取绑定提交中指定文件的完整 patch')
    def get_file_diff(file_path: str) -> str:
        for file in view().changed_files:
            if file_path in (file['path'], file.get('rename_from')):
                return file['diff_content']
        raise ValueError('该文件不在本次提交的差异中')

    @app.tool(description='读取绑定提交的用户需求原文')
    def get_prompts() -> list[dict]:
        return view().prompts

    if role == 'dev':
        from archguard.sync.prompts import record_prompt as append_prompt
        from archguard.sync.ledger import LedgerManager
        from archguard.sync.graph import GraphManager
        from archguard.sync.cursor import CursorManager
        from archguard.sync.lock import SyncLock
        from archguard.sync.schemas import CodeGraph
        leases = {}

        @app.tool(description='声明准备编辑的文件；检测有效租约重叠，冲突则失败')
        def begin_edit(ide_id: str, session_id: str, files: list[str], purpose: str) -> dict:
            from archguard.core.ledger_analyzer import normalize
            requested = {normalize(p) for p in files}
            unread, _ = CursorManager(root).get_unread_events(ide_id, session_id)
            for event in unread:
                affected = {normalize(p.file) for p in event.scope.files_changed} | {normalize(p) for p in event.scope.docs_changed}
                if event.source_ai_ide != ide_id and requested & affected:
                    raise ValueError('编辑范围与未确认的协同事件重叠，请先阅读并处理冲突: ' + event.version)
            manager = leases.setdefault((ide_id, session_id), SyncLock(root))
            obtained = []
            try:
                for path in sorted(requested):
                    manager.acquire_intent_lock(path, ide_id, purpose)
                    obtained.append(path)
            except Exception:
                for path in obtained:
                    manager.release_intent_lock(path)
                raise
            return {'locked_files': obtained}

        @app.tool(description='完成记账后释放当前服务会话自己持有的编辑意图')
        def end_edit(ide_id: str, session_id: str, files: list[str]) -> dict:
            manager = leases.get((ide_id, session_id))
            if manager is None:
                raise ValueError('当前服务会话没有持有这些租约')
            for path in files:
                manager.release_intent_lock(path)
            return {'released': files}

        @app.tool(description='维护人工语义或非 Python 图谱声明，保留原 Skill 全类型节点和边')
        def update_architecture_graph(graph_data: dict, ide_id: str, trigger_version: str) -> dict:
            from archguard.core.ledger_analyzer import normalize
            graph = CodeGraph.model_validate(graph_data)
            for node in graph.nodes:
                normalize(node)
                target = (Path(root) / node).resolve()
                if not target.is_relative_to(Path(root)) or not target.is_file():
                    raise ValueError('图谱声明包含不存在的项目文件')
            for edge in graph.edges:
                if edge.from_ not in graph.nodes or (edge.to not in graph.nodes and not edge.to.startswith('external:')):
                    raise ValueError('图谱依赖边引用不存在的节点')
            versions = {e.version for e in LedgerManager(root).read_all_events()}
            if trigger_version not in versions:
                raise ValueError('图谱变动必须关联真实账本版本')
            return GraphManager(root).update_graph(graph, ide_id, trigger_version).model_dump(mode='json', by_alias=True)

        @app.tool(description='逐条记录原始用户需求，绑定记录时的 Git 基线')
        def record_prompt(prompt_text: str) -> dict:
            return append_prompt(root, prompt_text)

        @app.tool(description='追加标准协同事件，自动维护账本流水和项目状态')
        def record_sync_event(event_data: dict) -> dict:
            return LedgerManager(root).append_event(event_data).model_dump(mode='json', by_alias=True)

        @app.tool(description='扫描源码并安全更新工作态图谱与变更日志')
        def sync_graph(ide_id: str, trigger_version: str = 'v0000') -> dict:
            if trigger_version != 'v0000' and trigger_version not in {e.version for e in LedgerManager(root).read_all_events()}:
                raise ValueError('图谱变动引用不存在的账本版本')
            return GraphManager(root).sync(ide_id, trigger_version).model_dump(mode='json', by_alias=True)

        @app.tool(description='创建独立协同会话，返回唯一会话 ID')
        def start_sync_session(ide_id: str) -> str:
            return CursorManager(root).start_session(ide_id)

        # 同一服务会话中保存已交付范围，只有读过的版本才允许推进。
        delivered = {}

        @app.tool(description='任务开始和编辑前读取所有未读事件以及当前图谱')
        def get_sync_updates(ide_id: str, session_id: str) -> dict:
            events, line = CursorManager(root).get_unread_events(ide_id, session_id)
            delivered[(ide_id, session_id)] = line
            return {'events': [e.model_dump(mode='json', by_alias=True) for e in events], 'last_line': line,
                    'graph': GraphManager(root).read_graph().model_dump(mode='json', by_alias=True)}

        @app.tool(description='确认已经理解本服务返回的未读事件后推进自己的会话游标')
        def acknowledge_sync(ide_id: str, session_id: str, last_line: int) -> dict:
            if delivered.get((ide_id, session_id)) != last_line:
                raise ValueError('不能跳过尚未读取的事件')
            CursorManager(root).update_cursor(ide_id, session_id, f'v{last_line:04d}', last_line)
            return {'last_read_line': last_line}

        @app.tool(description='提交前固定暂存树、需求与申报批次')
        def prepare_audit_commit() -> dict:
            return prepare_commit(root)

    return app


def run_mcp_server():
    parser = argparse.ArgumentParser(description='IDE_Audit MCP 服务')
    parser.add_argument('--project-root', required=True)
    parser.add_argument('--role', choices=['dev', 'audit'], default='audit')
    parser.add_argument('--audit-id')
    args = parser.parse_args()
    create_server(args.project_root, args.role, args.audit_id).run(transport='stdio')


if __name__ == '__main__':
    run_mcp_server()
