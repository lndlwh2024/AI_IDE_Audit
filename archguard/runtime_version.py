"""区分内存中的服务版本与磁盘安装版本，升级后旧服务不得继续业务操作。"""
import os
import re
from pathlib import Path
from archguard import __version__


def installed_version():
    text = (Path(__file__).parent / '__init__.py').read_text(encoding='utf-8')
    match = re.search(r'__version__\s*=\s*[\"\']([^\"\']+)', text)
    return match.group(1) if match else None


def info():
    disk = installed_version()
    return {'running_version':__version__, 'installed_version':disk, 'pid':os.getpid(),
            'restart_required':disk != __version__,
            'capabilities':['automatic_phase_binding','prepared_usage_count','b_report_panel']}


def require_current():
    value = info()
    if value['restart_required']:
        raise ValueError('IDE_Audit 已升级，但当前 MCP 仍运行旧版本；请刷新宿主 MCP 或完全退出后重启 Codex。停止业务操作，不重复记账或提交。')
