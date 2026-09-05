import os
import stat
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

HOOK_CONTENT = """#!/bin/sh
# 触发 archguard audit
echo "Triggering archguard audit..."
archguard audit
"""

def install_post_commit_hook(project_root: str) -> bool:
    """
    安装 post-commit hook
    """
    git_dir = Path(project_root) / ".git"
    if not git_dir.exists():
        logger.warning("非 git 仓库，跳过安装 hook")
        return False
        
    hook_path = git_dir / "hooks" / "post-commit"
    
    try:
        with open(hook_path, "w", encoding="utf-8") as f:
            f.write(HOOK_CONTENT)
        
        # 赋予执行权限
        st = os.stat(hook_path)
        os.chmod(hook_path, st.st_mode | stat.S_IEXEC)
        logger.info("已安装 post-commit hook")
        return True
    except Exception as e:
        logger.error(f"安装 hook 失败: {e}")
        return False

def uninstall_post_commit_hook(project_root: str) -> bool:
    """
    卸载 post-commit hook
    """
    hook_path = Path(project_root) / ".git" / "hooks" / "post-commit"
    if hook_path.exists():
        try:
            hook_path.unlink()
            logger.info("已卸载 post-commit hook")
            return True
        except Exception as e:
            logger.error(f"卸载 hook 失败: {e}")
            return False
    return True
