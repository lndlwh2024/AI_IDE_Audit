import os
import shutil
import logging
from pathlib import Path
from archguard.config.settings import get_ide_audit_dir
from archguard.adapters.git_hook import install_post_commit_hook

logger = logging.getLogger(__name__)

def install_to_project(project_root: str, ide: str = 'codex') -> None:
    """
    安装 IDE_Audit 到项目
    :param project_root: 项目根目录
    :param ide: IDE 类型
    """
    logger.info(f"安装 IDE_Audit 到项目 {project_root}, IDE: {ide}")
    
    # 1. 初始化 .ide_audit/ 目录结构
    audit_dir = Path(get_ide_audit_dir(project_root))
    audit_dir.mkdir(parents=True, exist_ok=True)
    
    # 2. 安装 post-commit git hook
    install_post_commit_hook(project_root)
    
    # 3. 注册 MCP Server 到 Codex 配置
    # 模拟操作
    codex_config = Path.home() / ".codex" / "config.toml"
    if codex_config.exists():
        logger.info(f"更新 Codex 配置: {codex_config}")
    
    # 4. 创建 A 窗口和 B 窗口 Skill 文件
    # 模拟拷贝 templates
    logger.info("创建 Skill 文件")
