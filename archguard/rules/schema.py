"""审计规则数据结构定义

使用 Pydantic 模型保证规则定义的类型安全与校验。
分为两类模型：
- AuditRule：规则定义（从 YAML 加载）
- ArchitectureSignal：规则命中后产出的客观信号
"""

from enum import Enum
from pydantic import BaseModel, Field


class Severity(str, Enum):
    """严重级别枚举

    HIGH 表示可能造成架构层面破坏的关键变更；
    MEDIUM 表示需要关注但影响相对可控的变更。
    """
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"


class Dimension(str, Enum):
    """9大架构变更检测维度

    每个维度对应一类特定的架构关注点，
    规则引擎通过这些维度分类扫描 diff 中的物理特征。
    """
    DIR_STRUCTURE = "文件/目录结构变更"
    DB_SCHEMA = "数据库Schema变更"
    API_INTERFACE = "API/接口变更"
    MODULE_MERGE_SPLIT = "模块合并/拆分"
    SECURITY_BOUNDARY = "安全边界变更"
    EXECUTION_MODEL = "执行模型变更"
    DEPENDENCY_BOUNDARY = "模块依赖边界变更"
    CONFIG_ENV = "配置/环境变更"
    SHARED_CONTRACT = "共享契约变更"


class AuditRule(BaseModel):
    """单条审计规则定义

    从 default_rules.yaml 加载后经 Pydantic 校验。
    file_patterns 用于匹配变更文件路径（glob 格式），
    content_patterns 用于匹配代码内容中的特征（正则表达式）。
    两类 pattern 满足任一即视为命中。
    """
    id: str = Field(description="规则唯一标识，如 DIR_STRUCTURE_CHANGE")
    dimension: Dimension = Field(description="所属检测维度")
    severity: Severity = Field(description="严重级别")
    description: str = Field(description="规则的人类可读说明")
    file_patterns: list[str] = Field(
        default_factory=list,
        description="文件路径匹配模式列表（glob 格式，如 '**/migrations/**'）",
    )
    content_patterns: list[str] = Field(
        default_factory=list,
        description="代码内容匹配模式列表（正则表达式）",
    )


class ArchitectureSignal(BaseModel):
    """规则命中后产出的客观架构变更信号

    每个信号代表一次具体的规则触发事件，
    包含触发的规则、文件及匹配详情。
    这是纯粹的物理事实描述，不包含任何主观判断。
    """
    rule_id: str = Field(description="触发的规则 ID")
    dimension: Dimension = Field(description="检测维度")
    severity: Severity = Field(description="严重级别")
    file_path: str = Field(description="触发文件路径")
    description: str = Field(description="客观信号描述")
    matched_pattern: str = Field(description="具体命中的模式（glob 或正则）")
