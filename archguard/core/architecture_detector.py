"""架构变更信号检测器

将 diff_analyzer 的物理事实输出与 rules 的规则定义进行模式匹配。
只做客观特征检测，不做合理性判断——判断权归 B 窗口 LLM。

检测逻辑：
    1. 文件路径 glob 匹配（file_patterns）
    2. 代码内容正则匹配（content_patterns）
    3. 特殊结构检测（目录级新增/删除、文件重命名/移动）
"""

import fnmatch
import logging
import re
from pathlib import PurePosixPath

from archguard.core.diff_analyzer import DiffResult, FileChange
from archguard.rules.schema import ArchitectureSignal, AuditRule, Dimension

logger = logging.getLogger(__name__)


def detect_signals(
    diff_result: DiffResult, rules: list[AuditRule]
) -> list[ArchitectureSignal]:
    """扫描 diff 结果，返回命中的架构变更客观信号列表

    遍历每个变更文件，与每条规则进行匹配。
    同时执行特殊结构检测（目录增删、文件重命名）。

    Args:
        diff_result: diff_analyzer 产出的变更事实
        rules: 加载的审计规则列表

    Returns:
        命中的架构变更信号列表（纯物理事实，不含主观判断）
    """
    signals: list[ArchitectureSignal] = []

    for file_change in diff_result.files:
        # 1. 特殊结构检测：目录级新增/删除
        # 原因：新增或删除整个目录层级往往意味着新模块的引入或旧模块废弃，属于高危架构动作
        signals.extend(_detect_dir_structure(file_change))

        # 2. 特殊结构检测：文件重命名/移动
        # 原因：文件重命名和移动可能伴随模块拆分或重构，需由审计 LLM 重点审查其意图
        signals.extend(_detect_module_rename(file_change))

        # 3. 规则驱动检测：遍历所有规则
        for rule in rules:
            # 跳过需要特殊处理的规则（已在上面单独处理）
            # 原因：结构增删与重命名已在专用函数中基于 Git 状态精确判定，避免规则遍历产生冗余或冲突信号
            if rule.id in ("DIR_STRUCTURE_NEW_DELETE", "MODULE_RENAME_MOVE"):
                continue
            signal = _match_rule(file_change, rule)
            if signal:
                signals.append(signal)

    logger.info("检测到 %d 个架构变更信号", len(signals))
    return signals


def _detect_dir_structure(file_change: FileChange) -> list[ArchitectureSignal]:
    """检测目录级别的新增或删除

    当一个新增或删除的文件位于新的目录路径下（含子目录），
    视为可能的目录结构变更。
    仅对文件新增（A）或删除（D）类型触发。
    """
    signals = []
    # 边界防御：仅当文件为新增或删除时才可能导致目录结构的创建或消失
    if file_change.change_type not in ("A", "D"):
        return signals

    # 如果文件路径包含目录层级，视为潜在的目录结构变更
    # 使用 PurePosixPath 统一处理 POSIX 风格的 git 相对路径
    parts = PurePosixPath(file_change.path).parts
    if len(parts) > 1:
        action = "新增" if file_change.change_type == "A" else "删除"
        signals.append(
            ArchitectureSignal(
                rule_id="DIR_STRUCTURE_NEW_DELETE",
                dimension=Dimension.DIR_STRUCTURE,
                severity="HIGH",
                file_path=file_change.path,
                description=f"检测到目录级文件{action}: {file_change.path}",
                matched_pattern=f"change_type={file_change.change_type}, depth={len(parts)}",
            )
        )
    return signals


def _detect_module_rename(file_change: FileChange) -> list[ArchitectureSignal]:
    """检测文件重命名/移动（可能涉及模块拆分或合并）"""
    signals = []
    # 边界条件：必须是重命名类型且必须包含原路径，防止缺失原路径导致误报
    if file_change.change_type != "R" or not file_change.rename_from:
        return signals

    signals.append(
        ArchitectureSignal(
            rule_id="MODULE_RENAME_MOVE",
            dimension=Dimension.MODULE_MERGE_SPLIT,
            severity="HIGH",
            file_path=file_change.path,
            description=f"检测到文件重命名/移动: {file_change.rename_from} → {file_change.path}",
            matched_pattern=f"R: {file_change.rename_from} -> {file_change.path}",
        )
    )
    return signals


def _path_matches(file_path: str, pattern: str) -> bool:
    """检查文件路径是否匹配指定的 glob 模式

    支持标准 glob 以及带 **/ 前缀的模式在根目录和子目录下的匹配。
    """
    norm_path = file_path.replace("\\", "/")
    posix_path = PurePosixPath(norm_path)

    # 1. 优先使用 pathlib.PurePosixPath.match
    if posix_path.match(pattern):
        return True

    # 2. fnmatch 备用
    if fnmatch.fnmatch(norm_path, pattern):
        return True

    # 3. 处理 **/ 前缀在根目录文件（无前置目录）下的匹配
    if pattern.startswith("**/"):
        stripped_pattern = pattern[3:]
        if fnmatch.fnmatch(norm_path, stripped_pattern) or posix_path.match(stripped_pattern):
            return True

    return False


def _match_rule(
    file_change: FileChange, rule: AuditRule
) -> ArchitectureSignal | None:
    """将单个文件变更与单条规则进行匹配

    匹配逻辑（满足任一即命中）：
    1. file_patterns: 文件路径 glob 匹配
    2. content_patterns: 对真实 patch 中的新增和删除内容执行正则匹配。
    """
    # 文件路径 glob 匹配
    for pattern in rule.file_patterns:
        if _path_matches(file_change.path, pattern):
            return ArchitectureSignal(
                rule_id=rule.id,
                dimension=rule.dimension,
                severity=rule.severity,
                file_path=file_change.path,
                description=rule.description,
                matched_pattern=f"file: {pattern}",
            )

    changed_lines = []
    in_hunk = False
    for line in file_change.diff_content.splitlines():
        if line.startswith('@@ '):
            in_hunk = True
        elif in_hunk and line.startswith(('+', '-')):
            changed_lines.append(line[1:])
    changed_text = '\n'.join(changed_lines)
    # 内容正则匹配仅使用变动行，避免把未改动上下文作为变化。
    # 异常防御：外部规则正则可能不合法，捕获 re.error 防止单条非法规则中断整个审计流程
    for pattern in rule.content_patterns:
        try:
            if re.search(pattern, changed_text, re.MULTILINE):
                return ArchitectureSignal(
                    rule_id=rule.id,
                    dimension=rule.dimension,
                    severity=rule.severity,
                    file_path=file_change.path,
                    description=rule.description,
                    matched_pattern=f"content(diff): {pattern}",
                )
        except re.error:
            logger.warning("正则表达式无效，跳过: %s", pattern)
            continue

    return None


def summarize_signals(
    signals: list[ArchitectureSignal],
) -> dict:
    """汇总架构信号统计

    按维度和严重级别分组统计，供审计报告使用。
    """
    summary: dict = {
        "total": len(signals),
        "by_severity": {"HIGH": 0, "MEDIUM": 0},
        "by_dimension": {},
    }
    for sig in signals:
        # 统计严重级别计数
        summary["by_severity"][sig.severity] = (
            summary["by_severity"].get(sig.severity, 0) + 1
        )
        # 兼容处理：维度可能是枚举类型 Dimension，也可能是已序列化的字符串
        dim_key = sig.dimension if isinstance(sig.dimension, str) else sig.dimension.value
        summary["by_dimension"][dim_key] = (
            summary["by_dimension"].get(dim_key, 0) + 1
        )
    return summary
