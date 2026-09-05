import logging
from typing import Any
from pydantic import BaseModel, Field

# 初始化日志记录器
logger = logging.getLogger(__name__)

class LedgerVerificationResult(BaseModel):
    """
    记账出入核验结果模型。
    用于体现代码改动与记账本声明的一致性。
    """
    is_consistent: bool = Field(description="实际修改和记账本是否完全一致")
    undeclared_files: list[str] = Field(default_factory=list, description="瞒报的文件（Diff有但记账无）")
    phantom_files: list[str] = Field(default_factory=list, description="虚报的文件（记账有但Diff无）")
    line_deviations: list[dict] = Field(default_factory=list, description="行号范围偏差详情")
    total_diff_files: int = Field(default=0, description="实际修改文件总数")
    total_ledger_files: int = Field(default=0, description="声明修改文件总数")
    consistency_score: float = Field(default=0.0, description="0.0~1.0之间的一致性评分")


def extract_diff_files(diff_result: Any) -> set[str]:
    """
    从 DiffResult 提取实际修改的文件路径集合。
    
    为什么这样设计：通过属性检查兼容未知的具体实现细节，保证在只读模式下的安全提取。
    """
    if hasattr(diff_result, "files"):
        return {f.path for f in diff_result.files}
    return set()


def extract_ledger_files(ledger_events: list[dict]) -> set[str]:
    """
    从记账本事件提取声明修改的文件路径集合。
    
    复杂逻辑解释：遍历所有事件中的 scope 范围，统一提取代码文件和文档文件的修改声明。
    """
    files = set()
    for event in ledger_events:
        scope = event.get("scope", {})
        # 收集变更的代码文件
        for fc in scope.get("files_changed", []):
            if "file" in fc:
                files.add(fc["file"])
        # 收集变更的文档文件
        for doc in scope.get("docs_changed", []):
            files.add(doc)
    return files


def check_line_range_deviation(diff_result: Any, ledger_events: list[dict]) -> list[dict]:
    """
    比对声明行号与实际修改行号的偏差。
    （目前提供核心框架，具体 diff_content 解析依赖 DiffResult 内部的实现细节）
    """
    deviations = []
    
    # 汇总 ledger 中每个文件声明修改的行范围
    ledger_lines = {}
    for event in ledger_events:
        for fc in event.get("scope", {}).get("files_changed", []):
            file_path = fc.get("file")
            lines = fc.get("lines", [])
            if file_path:
                ledger_lines.setdefault(file_path, []).extend(lines)
                
    if not hasattr(diff_result, "files"):
        return deviations
        
    for f in diff_result.files:
        if f.path in ledger_lines:
            # TODO: 解析 f.diff_content 以提取真实行号变动，并与 ledger_lines[f.path] 做精确重叠判定。
            # 目前占位返回，用于演示核验器逻辑。
            pass
            
    return deviations


def verify_ledger_consistency(diff_result: Any, ledger_events: list[dict]) -> LedgerVerificationResult:
    """
    核心业务逻辑：比对 Git Diff 实际改动与记账本声明范围。
    纯集合运算，判断“瞒报”或“虚报”的情况。
    """
    logger.info("开始核验记账出入一致性")
    
    diff_files = extract_diff_files(diff_result)
    ledger_files = extract_ledger_files(ledger_events)
    
    # 计算差异集合
    undeclared_files = list(diff_files - ledger_files)
    phantom_files = list(ledger_files - diff_files)
    
    # 计算行号偏差
    line_deviations = check_line_range_deviation(diff_result, ledger_events)
    
    # 完全一致的要求：无瞒报、无虚报、无行号偏差
    is_consistent = len(undeclared_files) == 0 and len(phantom_files) == 0 and len(line_deviations) == 0
    
    # 简单一致性评分逻辑：差异量越小，评分越高
    union_files = len(diff_files | ledger_files)
    if union_files == 0:
        consistency_score = 1.0
    else:
        diff_count = len(undeclared_files) + len(phantom_files)
        consistency_score = max(0.0, 1.0 - (diff_count / union_files))
        
    logger.info(
        "记账核验完成，评分：%.2f，未声明文件：%d，虚假文件：%d",
        consistency_score, len(undeclared_files), len(phantom_files)
    )
    
    return LedgerVerificationResult(
        is_consistent=is_consistent,
        undeclared_files=undeclared_files,
        phantom_files=phantom_files,
        line_deviations=line_deviations,
        total_diff_files=len(diff_files),
        total_ledger_files=len(ledger_files),
        consistency_score=consistency_score
    )
