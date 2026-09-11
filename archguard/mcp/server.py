"""官方 MCP STDIO 服务。角色和工程路径在启动时绑定，不接受调用者升级权限。"""
import argparse
from pathlib import Path
from functools import wraps
from mcp.server.mcpserver.exceptions import ToolError
from mcp.server.mcpserver import MCPServer
from archguard.runtime import get_result, prepare_commit
from archguard.delivery import graph_summary, graph_slice, prepared_summary, audit_packet
import json


def create_server(project_root, role='audit', audit_id=None):
    if role not in ('dev', 'audit'):
        raise ValueError('未知服务角色')
    root = str(Path(project_root).resolve())
    app = MCPServer('ide-audit-' + role)
    def tool(**options):
        def register(fn):
            @wraps(fn)
            def checked(*args, **kwargs):
                from archguard.adapters.codex.session_manager import AppServerError
                try:
                    return fn(*args, **kwargs)
                except (ValueError, PermissionError, AppServerError) as exc:
                    raise ToolError(str(exc)) from exc
            return app.tool(**options)(checked)
        return register

    bound_id = audit_id
    from archguard import project_control as control

    @tool(description='查看本项目已记录 B token 用量；未知不填零，不代表账户额度')
    def get_token_usage() -> dict:
        from archguard.phase_usage import compact_b
        return compact_b(root)

    @tool(description='A 在检查账本/图谱前或提交后维护前，B 在审计前记录用量起点；传当前真实 Codex 任务 ID')
    def begin_token_phase(thread_id: str, phase: str) -> dict:
        from archguard.phase_usage import begin
        return begin(root, thread_id, phase, 'A' if role == 'dev' else 'B')

    @tool(description='阶段完成后立即读取本次与本窗口累计 token；把 display 原样展示给用户，未知不猜测')
    def finish_token_phase(measurement_id: str) -> dict:
        from archguard.phase_usage import finish
        return finish(root, measurement_id, 'A' if role == 'dev' else 'B')

    @tool(description='查询本项目是否获授权、暂停或等待 A 同步；不扫描源码')
    def get_project_status() -> dict:
        return control.status(root)

    @tool(description='仅在用户明确要求暂停本项目插件时调用；保留数据和聊天')
    def pause_project() -> dict:
        return control.pause(root)

    @tool(description='用户要求恢复已授权项目时调用；仅转为待 A 同步，B 不扫描项目')
    def resume_project() -> dict:
        return control.resume(root)


    def view():
        nonlocal bound_id
        result = get_result(root, bound_id)
        # 首次绑定后始终使用相同任务，避免用户追问过程中 HEAD 变化。
        bound_id = result.audit_id
        return result

    @tool(description='读取绑定提交的客观事实包，不重新执行或写入审计')
    def audit_changes() -> dict:
        return json.loads(audit_packet(view()))

    @tool(description='读取绑定提交的代码图谱快照')
    def get_architecture_graph(file_paths: list[str] | None = None) -> dict:
        result = view()
        if file_paths is not None and len(file_paths) > 10:
            raise ValueError('每次最多读取 10 个文件的关联图谱')
        graphs = {'physical_before': result.graph_before, 'physical_after': result.graph_after,
                  'declared_before': result.declared_graph_before, 'declared_after': result.declared_graph}
        values = {k: graph_slice(v, file_paths) if file_paths else graph_summary(v) for k,v in graphs.items()}
        if len(json.dumps(values, ensure_ascii=False)) > 24000:
            raise ValueError('关联图谱过大，请缩小文件范围')
        return values

    @tool(description='读取绑定提交的全部申报事件')
    def get_ledger_records() -> list[dict]:
        return view().ledger_events

    @tool(description='读取绑定提交中指定文件的完整 patch')
    def get_file_diff(file_path: str) -> str:
        for file in view().changed_files:
            if file_path in (file['path'], file.get('rename_from')):
                return file['diff_content']
        raise ValueError('该文件不在本次提交的差异中')

    @tool(description='读取绑定提交的用户需求原文')
    def get_prompts() -> list[dict]:
        return view().prompts

    if role == 'dev':
        from archguard.sync.prompts import record_prompt as append_prompt
        from archguard.sync.ledger import LedgerManager
        from archguard.sync.graph import GraphManager
        from archguard.sync.cursor import CursorManager
        from archguard.sync.lock import SyncLock, scopes_overlap
        from archguard.sync.schemas import CodeGraph
        from archguard.sync.workflow import SyncWorkflow
        from archguard.storage import transaction

        def synchronized(function):
            @wraps(function)
            def wrapped(*args, **kwargs):
                with control.guarded(root), transaction(root, 'workflow'):
                    SyncWorkflow(root).recover()
                    return function(*args, **kwargs)
            return wrapped

        @tool(description='读取最新提交的后台队列、B 标识与项目归属，供 A 打开 B')
        def get_audit_status() -> dict:
            from archguard.dispatch_queue import status
            return status(root, get_result(root).audit_id)

        @tool(description='领取同一个原生 B 的待审计消息；A 必须原文发送至返回的任务 ID，不能代判或重复领取')
        def claim_desktop_audit(audit_id: str) -> dict:
            from archguard.adapters.codex.desktop_bridge import claim
            with control.guarded(root):
                return claim(root, audit_id)

        @tool(description='从真实 B 新轮次回收裁决，校验请求号、提交和逐文件覆盖；不接受 A 提供的裁决内容')
        def collect_desktop_audit(audit_id: str) -> dict:
            from archguard.adapters.codex.desktop_bridge import collect
            from archguard.dispatch_queue import start_worker
            result = collect(root, audit_id)
            start_worker(root)
            return result

        @tool(description='用稳定操作 ID 完成事件、图谱和派生视图交接；失败后相同参数重试不会重复记账')
        def complete_sync_operation(operation_id: str, event_data: dict, session_id: str | None = None) -> dict:
            with control.guarded(root):
                return SyncWorkflow(root).complete(operation_id, event_data, session_id)

        @tool(description='恢复中断的协同交接，不重复追加原事件')
        def recover_sync_operation() -> dict:
            with control.guarded(root), transaction(root, 'workflow'):
                return SyncWorkflow(root).recover() or {'status': 'idle'}

        def wake_queue():
            from archguard.dispatch_queue import start_worker
            from archguard.storage import read_json, metadata_path
            if any(read_json(p).get('status') in ('queued', 'running') for p in metadata_path(root, 'queue').glob('*.json')):
                start_worker(root)

        leases = {}
        ready_sessions = set()

        @tool(description='声明准备编辑的文件；检测有效租约重叠，冲突则失败')
        @synchronized
        def begin_edit(ide_id: str, session_id: str, files: list[str], purpose: str) -> dict:
            if (ide_id, session_id) not in ready_sessions:
                raise ValueError('请先接入会话并建立或更新图谱，再开始编辑')
            from archguard.core.ledger_analyzer import normalize
            requested = {normalize(p) for p in files}
            unread, _ = CursorManager(root).get_unread_events(ide_id, session_id)
            for event in unread:
                affected = {normalize(p.file) for p in event.scope.files_changed} | {normalize(p) for p in event.scope.docs_changed}
                if event.source_ai_ide != ide_id and any(scopes_overlap(a, b) for a in requested for b in affected):
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

        @tool(description='完成记账后释放当前服务会话自己持有的编辑意图')
        @synchronized
        def end_edit(ide_id: str, session_id: str, files: list[str]) -> dict:
            manager = leases.get((ide_id, session_id))
            if manager is None:
                raise ValueError('当前服务会话没有持有这些租约')
            for path in files:
                manager.release_intent_lock(path)
            return {'released': files}

        @tool(description='维护人工语义或非 Python 图谱声明，保留原 Skill 全类型节点和边')
        @synchronized
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
            return graph_summary(GraphManager(root).update_graph(graph, ide_id, trigger_version).model_dump(mode='json', by_alias=True))

        @tool(description='逐条记录原始用户需求，绑定记录时的 Git 基线')
        def record_prompt(prompt_text: str) -> dict:
            with control.guarded(root):
                return append_prompt(root, prompt_text)

        @tool(description='追加标准协同事件，自动维护账本流水和项目状态')
        @synchronized
        def record_sync_event(event_data: dict) -> dict:
            return LedgerManager(root).append_event(event_data).model_dump(mode='json', by_alias=True)

        @tool(description='扫描源码并安全更新工作态图谱与变更日志')
        @synchronized
        def sync_graph(ide_id: str, trigger_version: str = 'v0000') -> dict:
            if trigger_version != 'v0000' and trigger_version not in {e.version for e in LedgerManager(root).read_all_events()}:
                raise ValueError('图谱变动引用不存在的账本版本')
            return graph_summary(GraphManager(root).sync(ide_id, trigger_version).model_dump(mode='json', by_alias=True))

        @tool(description='A 首次接入已授权项目：更新图谱和同步检查点，成功后才启用')
        def start_sync_session(ide_id: str) -> str:
            result = control.refresh_a(root, ide_id)
            session_id = result['session_id']
            ready_sessions.add((ide_id, session_id))
            wake_queue()
            return session_id

        @tool(description='只有 A 执行：恢复已授权项目的图谱和代码信息同步；B 不可调用')
        def enter_sync_session(ide_id: str, session_id: str) -> dict:
            ready_sessions.discard((ide_id, session_id))
            result = control.refresh_a(root, ide_id, session_id)
            ready_sessions.add((ide_id, session_id))
            wake_queue()
            return graph_summary(result['graph'])

        @tool(description='A 长时间编辑时续期自己持有的文件租约；失效时必须停止编辑并重新处理冲突')
        @synchronized
        def renew_edit(ide_id: str, session_id: str, files: list[str]) -> dict:
            manager = leases.get((ide_id, session_id))
            if manager is None:
                raise ValueError('当前服务会话没有持有这些租约')
            manager.renew_intent_locks(files)
            return {'renewed': files, 'lease_seconds': 600}


        # 同一服务会话中保存已交付范围，只有读过的版本才允许推进。
        delivered = {}
        event_chunks = {}

        @tool(description='分页读取增量账本，默认最多 10 条/12000 字符；无新事件不发送全图，确认当前页后再读下一页')
        def get_sync_updates(ide_id: str, session_id: str, limit: int = 10) -> dict:
            control.require(root)
            events, line = CursorManager(root).get_unread_events(ide_id, session_id)
            if not 1 <= limit <= 20:
                raise ValueError('每页事件数须为 1 到 20')
            page, used = [], 0
            for event in events[:limit]:
                value = event.model_dump(mode='json', by_alias=True)
                size = len(json.dumps(value, ensure_ascii=False))
                if used + size > 12000 and page:
                    break
                if size > 12000:
                    raise ValueError('单条事件超过传输预算，请使用 get_sync_event_chunk 从 offset=0 分段读取后确认')
                page.append(value); used += size
            last = line - len(events) + len(page)
            delivered[(ide_id, session_id)] = last
            return {'events': page, 'last_line': last, 'total_line': line, 'has_more': last < line,
                    'graph': graph_summary(GraphManager(root).read_graph().model_dump(mode='json', by_alias=True))}

        @tool(description='分段读取首条超大未读事件；从 offset=0 顺序读取 next_offset，完整读完才允许确认，不能跳段')
        def get_sync_event_chunk(ide_id: str, session_id: str, offset: int = 0) -> dict:
            import hashlib
            control.require(root)
            events, total = CursorManager(root).get_unread_events(ide_id, session_id)
            if not events:
                return {'complete':True, 'text':'', 'last_line':total}
            serialized = json.dumps(events[0].model_dump(mode='json', by_alias=True), ensure_ascii=False)
            line = total - len(events) + 1
            digest = hashlib.sha256(serialized.encode()).hexdigest()
            key = (ide_id, session_id)
            if offset == 0:
                event_chunks[key] = (line, digest, 0)
                delivered.pop(key, None)
            if event_chunks.get(key) != (line, digest, offset) or offset < 0 or offset >= len(serialized):
                raise ValueError('事件发生变化或分段顺序错误，请从 offset=0 重读')
            end = min(offset + 6000, len(serialized))
            event_chunks[key] = (line, digest, end)
            complete = end == len(serialized)
            if complete:
                delivered[key] = line
            return {'version':events[0].version, 'text':serialized[offset:end], 'next_offset':end,
                    'complete':complete, 'last_line':line, 'encoding':'JSON 文本分段，按顺序阅读'}

        @tool(description='确认已经理解本服务返回的未读事件后推进自己的会话游标')
        @synchronized
        def acknowledge_sync(ide_id: str, session_id: str, last_line: int) -> dict:
            if delivered.get((ide_id, session_id)) != last_line:
                raise ValueError('不能跳过尚未读取的事件')
            CursorManager(root).update_cursor(ide_id, session_id, f'v{last_line:04d}', last_line)
            return {'last_read_line': last_line}

        @tool(description='提交前固定暂存树、需求与申报批次')
        def prepare_audit_commit() -> dict:
            with control.guarded(root):
                return prepared_summary(prepare_commit(root))

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
