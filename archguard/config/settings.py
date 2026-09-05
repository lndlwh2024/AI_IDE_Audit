"""IDE_Audit 全局配置与路径管理

集中管理 .ide_audit/ 数据目录的路径解析与自动创建。
采用方案 B：统一使用 .ide_audit/ 作为唯一数据根目录，
将原 dual-agent-sync 的 codegraph/ 和 collab/ 也整合其中。
所有文件操作均通过此模块获取路径，避免硬编码分散。
"""

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# IDE_Audit 本地数据目录名称（位于用户项目根目录下）
IDE_AUDIT_DIR = ".ide_audit"

# ════════════════════════════════════════════════════════════
# 审计专用子目录（IDE_Audit 原有功能）
# ════════════════════════════════════════════════════════════
PROMPTS_DIR = "prompts"
PROMPTS_ARCHIVED_DIR = "prompts/archived"
RESULTS_DIR = "results"
RESULTS_HISTORY_DIR = "results/history"
REPORTS_DIR = "reports"

# ════════════════════════════════════════════════════════════
# 协同与图谱子目录（继承自 dual-agent-sync，方案 B 整合）
# ════════════════════════════════════════════════════════════
CODEGRAPH_DIR = "codegraph"
CODEGRAPH_LOCKS_DIR = "codegraph/locks"
COLLAB_DIR = "collab"
COLLAB_CURSORS_DIR = "collab/cursors"
COLLAB_LOCKS_DIR = "collab/locks"


# ─── 审计根目录 ─────────────────────────────────────────────

def get_audit_root(project_root: str | Path) -> Path:
    """获取 .ide_audit/ 根目录的绝对路径"""
    return Path(project_root) / IDE_AUDIT_DIR


# ─── 审计专用路径 ────────────────────────────────────────────

def get_prompts_dir(project_root: str | Path) -> Path:
    """获取 prompts/ 目录路径"""
    return get_audit_root(project_root) / PROMPTS_DIR


def get_prompts_archived_dir(project_root: str | Path) -> Path:
    """获取 prompts/archived/ 目录路径"""
    return get_audit_root(project_root) / PROMPTS_ARCHIVED_DIR


def get_results_dir(project_root: str | Path) -> Path:
    """获取 results/ 目录路径"""
    return get_audit_root(project_root) / RESULTS_DIR


def get_results_history_dir(project_root: str | Path) -> Path:
    """获取 results/history/ 目录路径"""
    return get_audit_root(project_root) / RESULTS_HISTORY_DIR


def get_reports_dir(project_root: str | Path) -> Path:
    """获取 reports/ 目录路径"""
    return get_audit_root(project_root) / REPORTS_DIR


def get_pending_prompts_file(project_root: str | Path) -> Path:
    """获取 pending.json 文件路径"""
    return get_prompts_dir(project_root) / "pending.json"


def get_latest_result_file(project_root: str | Path) -> Path:
    """获取 latest.json 文件路径"""
    return get_results_dir(project_root) / "latest.json"


def get_session_file(project_root: str | Path) -> Path:
    """获取 session.json（B窗口 threadId 持久化）文件路径"""
    return get_audit_root(project_root) / "session.json"


# ─── 代码架构图谱路径（继承 dual-agent-sync codegraph 模块） ──

def get_codegraph_dir(project_root: str | Path) -> Path:
    """获取 codegraph/ 目录路径（代码架构图谱存放位置）"""
    return get_audit_root(project_root) / CODEGRAPH_DIR


def get_graph_file(project_root: str | Path) -> Path:
    """获取 graph.json 文件路径（全项目文件级架构图谱）"""
    return get_codegraph_dir(project_root) / "graph.json"


def get_graph_changelog_file(project_root: str | Path) -> Path:
    """获取 graph.changelog.jsonl 文件路径（图谱增量变更日志）"""
    return get_codegraph_dir(project_root) / "graph.changelog.jsonl"


def get_codegraph_locks_dir(project_root: str | Path) -> Path:
    """获取 codegraph/locks/ 目录路径（图谱写入排他锁）"""
    return get_audit_root(project_root) / CODEGRAPH_LOCKS_DIR


# ─── 协作记账路径（继承 dual-agent-sync collab 模块） ─────────

def get_collab_dir(project_root: str | Path) -> Path:
    """获取 collab/ 目录路径（协作记账模块根目录）"""
    return get_audit_root(project_root) / COLLAB_DIR


def get_ledger_file(project_root: str | Path) -> Path:
    """获取 ledger.jsonl 文件路径（协作事件账本，append-only）"""
    return get_collab_dir(project_root) / "ledger.jsonl"


def get_audit_log_file(project_root: str | Path) -> Path:
    """获取 AUDIT_LOG.md 文件路径（人类可读审计摘要）"""
    return get_collab_dir(project_root) / "AUDIT_LOG.md"


def get_project_state_file(project_root: str | Path) -> Path:
    """获取 PROJECT_STATE.md 文件路径（项目状态快照）"""
    return get_collab_dir(project_root) / "PROJECT_STATE.md"


def get_cursors_dir(project_root: str | Path) -> Path:
    """获取 collab/cursors/ 目录路径（各 AI IDE 读取游标）"""
    return get_audit_root(project_root) / COLLAB_CURSORS_DIR


def get_cursor_file(project_root: str | Path, ai_ide_id: str) -> Path:
    """获取指定 AI IDE 的游标文件路径"""
    return get_cursors_dir(project_root) / f"{ai_ide_id}.json"


def get_collab_locks_dir(project_root: str | Path) -> Path:
    """获取 collab/locks/ 目录路径（游标锁与编辑意图软锁）"""
    return get_audit_root(project_root) / COLLAB_LOCKS_DIR


# ─── 目录初始化 ─────────────────────────────────────────────

def ensure_directories(project_root: str | Path) -> None:
    """确保 .ide_audit/ 下所有子目录存在

    在首次使用或安装时调用，避免运行时因目录缺失而报错。
    使用 exist_ok=True 保证幂等性。
    包含审计专用目录和继承自 dual-agent-sync 的协同/图谱目录。
    """
    dirs = [
        # 审计专用目录
        get_prompts_dir(project_root),
        get_prompts_archived_dir(project_root),
        get_results_dir(project_root),
        get_results_history_dir(project_root),
        get_reports_dir(project_root),
        # 代码架构图谱目录（继承 dual-agent-sync）
        get_codegraph_dir(project_root),
        get_codegraph_locks_dir(project_root),
        # 协作记账目录（继承 dual-agent-sync）
        get_collab_dir(project_root),
        get_cursors_dir(project_root),
        get_collab_locks_dir(project_root),
    ]
    for d in dirs:
        d.mkdir(parents=True, exist_ok=True)
        logger.debug("确保目录存在: %s", d)
