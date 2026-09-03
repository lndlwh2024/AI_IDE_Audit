"""IDE_Audit 全局配置与路径管理

集中管理 .ide_audit/ 数据目录的路径解析与自动创建。
所有文件操作均通过此模块获取路径，避免硬编码分散。
"""

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# IDE_Audit 本地数据目录名称（位于用户项目根目录下）
IDE_AUDIT_DIR = ".ide_audit"

# 子目录常量
PROMPTS_DIR = "prompts"
PROMPTS_ARCHIVED_DIR = "prompts/archived"
RESULTS_DIR = "results"
RESULTS_HISTORY_DIR = "results/history"
REPORTS_DIR = "reports"


def get_audit_root(project_root: str | Path) -> Path:
    """获取 .ide_audit/ 根目录的绝对路径"""
    return Path(project_root) / IDE_AUDIT_DIR


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


def ensure_directories(project_root: str | Path) -> None:
    """确保 .ide_audit/ 下所有子目录存在

    在首次使用或安装时调用，避免运行时因目录缺失而报错。
    使用 exist_ok=True 保证幂等性。
    """
    dirs = [
        get_prompts_dir(project_root),
        get_prompts_archived_dir(project_root),
        get_results_dir(project_root),
        get_results_history_dir(project_root),
        get_reports_dir(project_root),
    ]
    for d in dirs:
        d.mkdir(parents=True, exist_ok=True)
        logger.debug("确保目录存在: %s", d)
