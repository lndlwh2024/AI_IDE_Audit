"""用户需求存储与生命周期管理

负责 A 窗口用户需求提示词的追加记录、读取与审计后归档清空。
采用追加模式（append），支持两次 commit 之间记录多条用户需求。

生命周期：
    record_prompt()  →  追加到 pending.json
    get_pending()    →  读取全部 pending
    archive_and_clear() → 归档到 archived/ 并清空 pending
"""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from archguard.config.settings import (
    ensure_directories,
    get_pending_prompts_file,
    get_prompts_archived_dir,
)

logger = logging.getLogger(__name__)


def record_prompt(project_root: str | Path, text: str) -> dict:
    """追加记录一条用户需求到 pending.json

    每条 prompt 附带 ISO 8601 时间戳，便于排序和回溯。
    采用追加模式而非覆盖，确保两次 commit 之间的所有用户意图都被完整捕获。

    Args:
        project_root: 用户项目根目录
        text: 用户需求原文

    Returns:
        本次记录的 prompt 条目（含时间戳）
    """
    if not text or not text.strip():
        raise ValueError("需求文本不能为空")

    ensure_directories(project_root)
    pending_file = get_pending_prompts_file(project_root)

    # 构造带时间戳的 prompt 条目
    entry = {
        "text": text.strip(),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    # 读取已有 pending 列表（首次使用时文件可能不存在）
    prompts = _read_pending(pending_file)
    prompts.append(entry)

    # 原子写入：先写完整内容再替换
    _write_json(pending_file, prompts)
    logger.info("记录第 %d 条需求 prompt", len(prompts))
    return entry


def get_pending_prompts(project_root: str | Path) -> list[dict]:
    """读取当前所有未审计的 prompt 列表

    Args:
        project_root: 用户项目根目录

    Returns:
        按时间顺序排列的 prompt 条目列表，
        每条包含 text 和 timestamp 字段。
        如果没有 pending 数据则返回空列表。
    """
    pending_file = get_pending_prompts_file(project_root)
    return _read_pending(pending_file)


def archive_and_clear(
    project_root: str | Path, commit_hash: str
) -> str | None:
    """将 pending prompts 归档并清空

    审计完成后调用：将当前 pending 内容打包归档到 archived/ 目录，
    然后清空 pending.json。归档文件名包含时间戳和 commit hash，
    便于回溯。

    Args:
        project_root: 用户项目根目录
        commit_hash: 本次审计对应的 commit hash

    Returns:
        归档文件路径字符串，如果 pending 为空则返回 None
    """
    ensure_directories(project_root)
    pending_file = get_pending_prompts_file(project_root)
    prompts = _read_pending(pending_file)

    if not prompts:
        logger.info("pending 为空，无需归档")
        return None

    # 生成归档文件名：时间戳_commit短hash.json
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    short_hash = commit_hash[:7] if len(commit_hash) >= 7 else commit_hash
    archive_name = f"{timestamp}_{short_hash}.json"
    archive_path = get_prompts_archived_dir(project_root) / archive_name

    # 归档当前 pending 数据
    _write_json(archive_path, prompts)
    logger.info("归档 %d 条 prompt 到: %s", len(prompts), archive_path)

    # 清空 pending
    _write_json(pending_file, [])
    logger.info("已清空 pending.json")

    return str(archive_path)


def _read_pending(pending_file: Path) -> list[dict]:
    """安全读取 pending.json，文件不存在或格式错误时返回空列表"""
    if not pending_file.exists():
        return []
    try:
        with open(pending_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            return data
        logger.warning("pending.json 格式异常（非列表），将重置为空")
        return []
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("读取 pending.json 失败: %s，将重置为空", e)
        return []


def _write_json(path: Path, data: list) -> None:
    """安全写入 JSON 文件"""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
