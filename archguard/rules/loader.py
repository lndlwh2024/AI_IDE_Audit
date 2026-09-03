"""审计规则加载器

从内置 YAML 文件或用户自定义路径加载规则，
经 Pydantic 校验后返回类型安全的规则列表。
"""

import logging
from pathlib import Path

import yaml

from archguard.rules.schema import AuditRule

logger = logging.getLogger(__name__)

# 内置默认规则文件路径（与本文件同目录）
_DEFAULT_RULES_PATH = Path(__file__).parent / "default_rules.yaml"


def load_rules(path: str | Path) -> list[AuditRule]:
    """从指定 YAML 文件加载审计规则

    Args:
        path: 规则 YAML 文件路径

    Returns:
        经 Pydantic 校验的 AuditRule 列表

    Raises:
        FileNotFoundError: 规则文件不存在
        yaml.YAMLError: YAML 格式错误
        pydantic.ValidationError: 规则字段校验失败
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"规则文件不存在: {path}")

    logger.info("加载规则文件: %s", path)
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    raw_rules = data.get("rules", [])
    rules = [AuditRule(**r) for r in raw_rules]
    logger.info("成功加载 %d 条规则", len(rules))
    return rules


def load_default_rules() -> list[AuditRule]:
    """加载内置默认规则集

    Returns:
        默认的 9 大维度审计规则列表
    """
    return load_rules(_DEFAULT_RULES_PATH)
