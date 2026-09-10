"""只读检查项目选择；不安装、不扫描源码、不代替用户授权。"""
import argparse
import os
import time
import getpass
import hashlib
import json
import platform
import subprocess
import sys
from pathlib import Path


def check(event):
    cwd = event.get('cwd')
    if not cwd:
        return {}
    result = subprocess.run(['git', '-C', cwd, 'rev-parse', '--show-toplevel'],
                            capture_output=True, text=True, encoding='utf-8', timeout=5)
    if result.returncode:
        return {}
    root = Path(result.stdout.strip()).resolve()
    base = root / '.ide_audit'
    if base.is_symlink() or (base.exists() and base.resolve() != base):
        return {}
    try:
        state = json.loads((base / 'project-control.json').read_text(encoding='utf-8'))
        expected = {'root': str(root), 'host': hashlib.sha256(
            (platform.node() + '\0' + getpass.getuser()).encode()).hexdigest()}
        if state.get('identity') != expected or not state.get('project_id'):
            state = {}
    except (ValueError, OSError, TypeError):
        state = {}
    try:
        session = json.loads((base / 'session.json').read_text(encoding='utf-8'))
    except (ValueError, OSError):
        session = {}
    if event.get('session_id') and event.get('session_id') == session.get('thread_id'):
        text = '你是审计 B。不得执行 A 的项目扫描或恢复同步。只核查固定证据，缺证请 A 补齐。'
    elif state.get('status') == 'enabled':
        text = '当前项目已授权 IDE_Audit。A 开始编码前必须调用 enter_sync_session（新任务用 start_sync_session）刷新图谱。'
    elif state.get('status') == 'pending_a':
        text = '项目已授权，正在等待 A 更新图谱和代码同步。只有 A 完成接入后才能启用自动审计；B 不扫描。'
    elif state.get('status') in ('declined', 'paused'):
        text = '当前项目 IDE_Audit 已拒绝或暂停，不运行自动功能、不重复询问；仅响应用户主动开启/恢复。'
    else:
        text = ('当前项目尚未授权 IDE_Audit。请 A 在本轮首次工作时询问是否开启全套图谱、同步、需求记录及提交后 B 审计，'
                '说明会使用 Codex 额度。未得到明确同意不执行任何插件业务操作；不妨碍普通开发。'
                '同意后使用 ide-audit Skill 的安装脚本并传 --consent，仅授权当前项目。')
    return {'hookSpecificOutput': {'hookEventName': 'SessionStart', 'additionalContext': text}}


def decline(cwd, confirmed=False):
    if not confirmed:
        raise ValueError('需要用户明确拒绝')
    root = Path(cwd).resolve(strict=True)
    result = subprocess.run(['git', '-C', str(root), 'rev-parse', '--show-toplevel'], capture_output=True,
                            text=True, encoding='utf-8', timeout=5, check=True)
    if Path(result.stdout.strip()).resolve() != root:
        raise ValueError('请指定项目根目录')
    base = root / '.ide_audit'
    if base.is_symlink() or (base.exists() and base.resolve() != base):
        raise ValueError('项目数据目录不能重定向')
    base.mkdir(exist_ok=True)
    target = base / 'project-control.json'
    if target.exists():
        raise ValueError('项目已有选择，请使用已安装运行环境的 decline 或 pause 命令')
    state = {'identity': {'root': str(root), 'host': hashlib.sha256(
        (platform.node() + '\0' + getpass.getuser()).encode()).hexdigest()},
        'project_id': 'local-declined', 'status': 'declined', 'revision': 1, 'epoch': 1,
        'changed_at': time.time()}
    # 排他创建，不能覆盖其他窗口同时授权的记录。
    with target.open('x', encoding='utf-8') as stream:
        json.dump(state, stream, ensure_ascii=True)
    return state


if __name__ == '__main__':
    if '--decline' in sys.argv:
        parser = argparse.ArgumentParser()
        parser.add_argument('--decline', action='store_true')
        parser.add_argument('--confirmed', action='store_true')
        parser.add_argument('--project-root', required=True)
        args = parser.parse_args()
        print(json.dumps(decline(args.project_root, args.confirmed), ensure_ascii=True))
    else:
        try:
            print(json.dumps(check(json.load(sys.stdin)), ensure_ascii=True))
        except Exception:
            print('{}')
