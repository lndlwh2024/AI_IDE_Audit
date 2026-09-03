"""审计主引擎 — 编排物理事实收集与架构信号扫描

核心编排流程：
    1. 调用 diff_analyzer 提取最后一次 commit 的物理变更事实
    2. 调用 prompt_store 读取两次 commit 之间的全部用户需求
    3. 调用 rules.loader 加载审计规则
    4. 调用 architecture_detector 执行 9 大维度规则扫描
    5. 归档 pending prompts
    6. 组装客观事实数据包并持久化保存

本引擎不做任何语义判断，只产出客观事实供 B 窗口 LLM 裁决。
"""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from pydantic import BaseModel, Field

from archguard.config.settings import (
    ensure_directories,
    get_latest_result_file,
    get_results_history_dir,
)
from archguard.core.architecture_detector import detect_signals, summarize_signals
from archguard.core.diff_analyzer import analyze_commit
from archguard.core.prompt_store import archive_and_clear, get_pending_prompts
from archguard.rules.loader import load_default_rules

logger = logging.getLogger(__name__)


class AuditResult(BaseModel):
    """客观事实审计结果数据包

    此结构由引擎产出，通过 MCP 接口（audit_changes 工具）
    提供给 B 窗口的审计 LLM。包含纯粹的物理事实与用户需求原文，
    不含任何合理性判断或通过/不通过结论。
    """
    # 时间与版本：记录审计发生的绝对时间与关联的 Git Commit 信息
    timestamp: str = Field(description="审计执行时间（ISO 8601）")
    commit_hash: str = Field(description="本次审计的 commit hash")
    commit_message: str = Field(description="commit message")

    # 用户需求：记录两次 commit 之间的全部 prompt，为后续 LLM 语义裁决提供需求证据链
    prompts: list[dict] = Field(
        default_factory=list,
        description="两次 commit 之间的全部用户需求原文与时间戳",
    )

    # Diff 摘要与文件明细：纯客观的代码改动物理指标
    diff_summary: dict = Field(
        default_factory=dict,
        description="变更统计摘要（文件总数、增删行数）",
    )
    changed_files: list[dict] = Field(
        default_factory=list,
        description="每个变更文件的详情（路径、类型、增删行数）",
    )

    # 架构变更客观信号与统计：基于规则引擎匹配出的客观事实信号
    architecture_signals: list[dict] = Field(
        default_factory=list,
        description="命中的架构变更客观信号列表",
    )
    signal_summary: dict = Field(
        default_factory=dict,
        description="架构信号按维度和严重级别的统计汇总",
    )


def run_audit(project_root: str | Path) -> AuditResult:
    """执行完整的审计分析流程

    编排所有核心模块，产出客观事实数据包。
    审计范围严格限定为最后一次 commit（HEAD~1..HEAD）。

    Args:
        project_root: 用户项目根目录（必须是有效的 Git 仓库）

    Returns:
        AuditResult 客观事实数据包
    """
    # 路径安全性防御：统一转为 Path 对象并初始化所需审计元数据目录
    project_root = Path(project_root)
    ensure_directories(project_root)

    logger.info("===== IDE_Audit 审计引擎启动 =====")
    logger.info("项目路径: %s", project_root)

    # ① 提取最后一次 commit 的物理变更事实（仅物理层面，不作推测）
    logger.info("步骤 1/5: 提取 Git Diff 物理事实")
    diff_result = analyze_commit(project_root)

    # ② 读取两次 commit 之间的全部用户需求（由 IDE Skill 写入的 prompt 日志）
    logger.info("步骤 2/5: 读取用户需求 prompts")
    prompts = get_pending_prompts(project_root)
    logger.info("读取到 %d 条用户需求", len(prompts))

    # ③ 加载内建审计规则库
    logger.info("步骤 3/5: 加载审计规则")
    rules = load_default_rules()

    # ④ 执行 9 大维度架构信号扫描
    logger.info("步骤 4/5: 执行架构变更信号扫描")
    signals = detect_signals(diff_result, rules)
    signal_summary = summarize_signals(signals)

    # ⑤ 归档 pending prompts（以 commit hash 命名归档，并重置待处理队列）
    # 原因：确保每次 commit 对应的 prompts 都有据可查，且不会泄漏到下一个 commit 周期
    logger.info("步骤 5/5: 归档 prompts")
    archive_and_clear(project_root, diff_result.commit_hash)

    # 组装客观事实数据包（严格保持数据不可篡改性与客观性）
    audit_result = AuditResult(
        timestamp=datetime.now(timezone.utc).isoformat(),
        commit_hash=diff_result.commit_hash,
        commit_message=diff_result.commit_message,
        prompts=prompts,
        diff_summary={
            "total_files_changed": diff_result.total_files_changed,
            "total_additions": diff_result.total_additions,
            "total_deletions": diff_result.total_deletions,
        },
        changed_files=[f.to_dict() for f in diff_result.files],
        architecture_signals=[s.model_dump() for s in signals],
        signal_summary=signal_summary,
    )

    # 持久化保存审计结果供后续 MCP 工具快速读取及历史追踪
    _save_result(project_root, audit_result)

    logger.info("===== 审计引擎完成 =====")
    logger.info(
        "结果: %d 个文件变更, %d 个架构信号（HIGH: %d, MEDIUM: %d）",
        diff_result.total_files_changed,
        signal_summary["total"],
        signal_summary["by_severity"].get("HIGH", 0),
        signal_summary["by_severity"].get("MEDIUM", 0),
    )

    return audit_result


def _save_result(project_root: Path, result: AuditResult) -> None:
    """将审计结果持久化保存

    保存两份：
    1. latest.json：最近一次结果（覆盖写入，方便 MCP 工具低延迟读取）
    2. history/{timestamp}_{hash}.json：历史归档（便于版本溯源与复盘）
    """
    ensure_directories(project_root)
    result_dict = result.model_dump()

    # 保存 latest.json
    latest_file = get_latest_result_file(project_root)
    _write_json(latest_file, result_dict)
    logger.info("结果已保存到: %s", latest_file)

    # 保存历史归档
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    short_hash = result.commit_hash[:7]
    history_file = (
        get_results_history_dir(project_root)
        / f"{timestamp}_{short_hash}.json"
    )
    _write_json(history_file, result_dict)
    logger.info("历史归档已保存到: %s", history_file)


def _write_json(path: Path, data: dict) -> None:
    """安全写入 JSON 文件

    原因：保证父级目录在写入前必然存在，指定 UTF-8 编码避免多语言需求内容乱码
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
