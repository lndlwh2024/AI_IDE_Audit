import json
import sys
import logging
from typing import Any, Dict, List, Optional
from archguard.config.settings import get_repo_root
from archguard.sync.ledger import LedgerManager
from archguard.sync.graph import GraphManager
from archguard.core.diff_analyzer import DiffAnalyzer
from archguard.core.graph_analyzer import GraphAnalyzer
from archguard.core.ledger_analyzer import LedgerAnalyzer
from archguard.core.engine import AuditEngine

logger = logging.getLogger(__name__)

# Fallback MCP implementation
class FallbackMCPServer:
    def __init__(self, name: str):
        self.name = name
        self.tools = {}

    def tool(self, name: str, description: str):
        def decorator(func):
            self.tools[name] = {
                "func": func,
                "description": description
            }
            return func
        return decorator

    def run(self):
        logger.info(f"Starting Fallback MCP Server {self.name} on stdio")
        for line in sys.stdin:
            try:
                request = json.loads(line.strip())
                if request.get("method") == "tools/list":
                    response = {
                        "jsonrpc": "2.0",
                        "id": request.get("id"),
                        "result": {
                            "tools": [{"name": k, "description": v["description"]} for k, v in self.tools.items()]
                        }
                    }
                    print(json.dumps(response), flush=True)
                elif request.get("method") == "tools/call":
                    params = request.get("params", {})
                    tool_name = params.get("name")
                    args = params.get("arguments", {})
                    if tool_name in self.tools:
                        try:
                            result = self.tools[tool_name]["func"](**args)
                            response = {
                                "jsonrpc": "2.0",
                                "id": request.get("id"),
                                "result": {"content": [{"type": "text", "text": json.dumps(result)}]}
                            }
                        except Exception as e:
                            response = {
                                "jsonrpc": "2.0",
                                "id": request.get("id"),
                                "error": {"code": -32603, "message": str(e)}
                            }
                    else:
                        response = {
                            "jsonrpc": "2.0",
                            "id": request.get("id"),
                            "error": {"code": -32601, "message": "Method not found"}
                        }
                    print(json.dumps(response), flush=True)
            except Exception as e:
                logger.error(f"Error processing request: {e}")

try:
    from mcp.server import Server
    import mcp.server.stdio
    HAS_MCP = True
except ImportError:
    HAS_MCP = False

if HAS_MCP:
    app = Server("ide_audit")
else:
    app = FallbackMCPServer("ide_audit")

@app.tool("record_prompt", "记录用户原始需求（追加到 pending.json）")
def record_prompt(project_root: str, prompt_text: str) -> str:
    """记录用户需求"""
    try:
        from archguard.core.prompt_store import record_pending_prompt
        record_pending_prompt(project_root, prompt_text)
        return "Prompt recorded successfully."
    except Exception as e:
        return f"Error recording prompt: {e}"

@app.tool("record_sync_event", "标准化记录开发操作事件到 ledger.jsonl")
def record_sync_event(project_root: str, action: str, details: Dict[str, Any]) -> str:
    """记录同步事件"""
    try:
        lm = LedgerManager(project_root)
        lm.append_record(action, details)
        return "Sync event recorded successfully."
    except Exception as e:
        return f"Error recording sync event: {e}"

@app.tool("sync_graph", "增量更新代码架构图谱")
def sync_graph(project_root: str, changed_files: List[str]) -> str:
    """同步图谱"""
    try:
        gm = GraphManager(project_root)
        gm.update_nodes(changed_files)
        return "Graph synced successfully."
    except Exception as e:
        return f"Error syncing graph: {e}"

@app.tool("audit_changes", "获取阶段一客观分析报告包")
def audit_changes(project_root: str) -> Dict[str, Any]:
    """审计变更"""
    try:
        engine = AuditEngine(project_root)
        return engine.generate_report()
    except Exception as e:
        return {"error": str(e)}

@app.tool("get_architecture_graph", "只读查询图谱")
def get_architecture_graph(project_root: str) -> Dict[str, Any]:
    """获取图谱摘要"""
    try:
        ga = GraphAnalyzer(project_root)
        return ga.get_summary()
    except Exception as e:
        return {"error": str(e)}

@app.tool("get_ledger_records", "只读查询记账本")
def get_ledger_records(project_root: str, limit: int = 100) -> List[Dict[str, Any]]:
    """获取记账记录"""
    try:
        la = LedgerAnalyzer(project_root)
        return la.get_recent_records(limit)
    except Exception as e:
        return [{"error": str(e)}]

@app.tool("get_file_diff", "获取特定文件的 diff 片段")
def get_file_diff(project_root: str, file_path: str) -> str:
    """获取文件差异"""
    try:
        da = DiffAnalyzer(project_root)
        return da.get_file_diff(file_path)
    except Exception as e:
        return str(e)

@app.tool("get_prompts", "获取待审计 prompt")
def get_prompts(project_root: str) -> List[str]:
    """获取Prompts"""
    try:
        from archguard.core.prompt_store import get_pending_prompts
        return get_pending_prompts(project_root)
    except Exception as e:
        return []

def run_mcp_server():
    """运行 MCP 服务器"""
    if HAS_MCP:
        import asyncio
        async def _run():
            async with mcp.server.stdio.stdio_server() as (read_stream, write_stream):
                await app.run(
                    read_stream,
                    write_stream,
                    app.create_initialization_options()
                )
        asyncio.run(_run())
    else:
        app.run()
