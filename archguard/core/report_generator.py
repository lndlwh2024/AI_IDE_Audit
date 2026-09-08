"""客观事实报告生成器

将 AuditResult 渲染为 Markdown 格式的客观事实摘要报告。
此报告用于 CLI 终端本地查看或备用存档，
不包含任何通过/不通过的裁决结论（裁决由 B 窗口 LLM 负责）。
"""

import logging
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

logger = logging.getLogger(__name__)

# 模板随 Python 包发布，不依赖源码工作目录。
_TEMPLATES_DIR = Path(__file__).parent.parent / "templates"


def generate_report(audit_result_dict: dict) -> str:
    """将审计结果渲染为 Markdown 报告

    优先使用 Jinja2 外部模板进行排版渲染；若模板不可用或渲染失败，
    则无缝降级到内置纯文本拼接模式，保证审计产物的可用性。

    Args:
        audit_result_dict: AuditResult.model_dump() 的字典形式

    Returns:
        渲染后的 Markdown 文本
    """
    # 如果模板目录不存在则使用纯字符串模板降级，避免部署环境缺失模板文件时直接崩溃
    if not _TEMPLATES_DIR.exists():
        logger.warning("模板目录不存在，使用内置降级模板: %s", _TEMPLATES_DIR)
        return _fallback_report(audit_result_dict)

    env = Environment(
        loader=FileSystemLoader(str(_TEMPLATES_DIR)),
        autoescape=select_autoescape(default=False),
        trim_blocks=True,
        lstrip_blocks=True,
    )

    try:
        template = env.get_template("audit_report.md.j2")
        return template.render(**audit_result_dict)
    except Exception as e:
        logger.warning("模板渲染失败，使用降级模板: %s", e)
        return _fallback_report(audit_result_dict)


def _fallback_report(data: dict) -> str:
    """内置降级报告模板

    当 Jinja2 模板文件不可用时，使用纯 Python 字符串拼接生成报告。
    保证在极简环境或打包缺失资源时依然能输出完整的客观物理事实。
    """
    lines = []
    lines.append("# IDE_Audit 客观事实报告")
    lines.append("")

    lines.append(f"- **证据状态**: {data.get('analysis_status', 'unknown')}")
    for diagnostic in data.get('diagnostics', []):
        lines.append(f"- 证据诊断: {diagnostic}")
    lines.append(f"- **审计时间**: {data.get('timestamp', 'N/A')}")
    lines.append(f"- **Commit**: `{data.get('commit_hash', 'N/A')[:12]}`")
    lines.append(f"- **Commit Message**: {data.get('commit_message', 'N/A')}")
    lines.append("")

    # 用户需求原文字段渲染
    prompts = data.get("prompts", [])
    lines.append(f"## 用户需求（共 {len(prompts)} 条）")
    lines.append("")
    if prompts:
        for i, p in enumerate(prompts, 1):
            lines.append(f"{i}. {p.get('text', '')}  ")
            lines.append(f"   _({p.get('timestamp', '')})_")
    else:
        lines.append("_无记录的用户需求_")
    lines.append("")

    # 变更统计摘要
    diff_summary = data.get("diff_summary", {})
    lines.append("## 变更摘要")
    lines.append("")
    lines.append(f"| 指标 | 数值 |")
    lines.append(f"|:---|:---|")
    lines.append(f"| 变更文件总数 | {diff_summary.get('total_files_changed', 0)} |")
    lines.append(f"| 新增行数 | +{diff_summary.get('total_additions', 0)} |")
    lines.append(f"| 删除行数 | -{diff_summary.get('total_deletions', 0)} |")
    lines.append("")

    # 变更文件列表表格
    changed_files = data.get("changed_files", [])
    lines.append("## 变更文件清单")
    lines.append("")
    lines.append("| 文件路径 | 类型 | +行 | -行 |")
    lines.append("|:---|:---:|:---:|:---:|")
    for f in changed_files:
        lines.append(
            f"| `{f.get('path', '')}` | {f.get('change_type', '')} "
            f"| +{f.get('additions', 0)} | -{f.get('deletions', 0)} |"
        )
    lines.append("")

    # 架构变更客观信号列表
    signals = data.get("architecture_signals", [])
    signal_summary = data.get("signal_summary", {})
    lines.append(f"## 架构变更信号（共 {signal_summary.get('total', 0)} 个）")
    lines.append("")
    if signals:
        lines.append("| 维度 | 严重级别 | 文件 | 描述 |")
        lines.append("|:---|:---:|:---|:---|")
        for s in signals:
            severity_icon = "🔴" if s.get("severity") == "HIGH" else "🟠"
            lines.append(
                f"| {s.get('dimension', '')} | {severity_icon} {s.get('severity', '')} "
                f"| `{s.get('file_path', '')}` | {s.get('description', '')} |"
            )
    else:
        lines.append("_未检测到架构变更信号_")
    lines.append("")

    # 图谱拓扑变动
    graph = data.get("graph_analysis")
    if graph:
        lines.append("## 图谱拓扑变动")
        lines.append(f"- 是否有变化: {graph.get('has_topology_changes', False)}")
        lines.append(f"- 新增节点: {len(graph.get('nodes_added', []))}")
        lines.append(f"- 删除节点: {len(graph.get('nodes_removed', []))}")
        lines.append(f"- 新增边: {len(graph.get('edges_added', []))}")
        lines.append(f"- 删除边: {len(graph.get('edges_removed', []))}")
        violations = graph.get("cross_module_violations", [])
        lines.append(f"- 跨模块违规: {len(violations)}")
        lines.append(f"- 循环依赖: {len(graph.get('cycles_detected', []))}")

        if violations:
            lines.append("")
            lines.append("| 源文件 | 目标文件 | 源模块 | 目标模块 | 边类型 |")
            lines.append("|:---|:---|:---|:---|:---|")
            for v in violations:
                lines.append(f"| {v.get('from_file', '')} | {v.get('to_file', '')} | {v.get('from_module', '')} | {v.get('to_module', '')} | {v.get('edge_type', '')} |")
        lines.append("")

    # 记账出入核验
    ledger = data.get("ledger_verification")
    if ledger:
        lines.append("## 记账出入核验")
        lines.append(f"- 是否一致: {ledger.get('is_consistent', False)}")
        score = ledger.get('consistency_score', 0.0) * 100
        lines.append(f"- 一致性评分: {score:.1f}%")
        lines.append(f"- 实际修改文件: {ledger.get('total_diff_files', 0)}")
        lines.append(f"- 声明修改文件: {ledger.get('total_ledger_files', 0)}")

        undeclared = ledger.get("undeclared_files", [])
        if undeclared:
            lines.append("### 未声明修改（瞒报）")
            for f in undeclared:
                lines.append(f"- `{f}`")

        phantom = ledger.get("phantom_files", [])
        if phantom:
            lines.append("### 虚报修改")
            for f in phantom:
                lines.append(f"- `{f}`")
        lines.append("")

    # 尾部法律与裁决权声明
    lines.append("---")
    lines.append("")
    lines.append("> 本报告由 IDE_Audit 规则引擎自动生成，仅包含客观物理事实。")
    lines.append("> 最终审计裁决（通过/不通过）由 B 窗口审计 LLM 负责。")

    return "\n".join(lines)
