"""MCP 服务包；延迟导入，避免模块启动时重复注册。"""


def run_mcp_server():
    from .server import run_mcp_server as run
    return run()
