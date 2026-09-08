"""保留现有 Hook 的管理器，按 Git 实际 hooksPath/worktree 解析路径。"""
import hashlib
import shlex
import stat
import sys
from pathlib import Path
import git
from archguard.storage import atomic_text, atomic_json, metadata_path, read_json


def hook_path(project_root):
    repo = git.Repo(project_root)
    path = Path(repo.git.rev_parse('--path-format=absolute', '--git-path', 'hooks/post-commit'))
    if path.is_symlink():
        raise ValueError('不能覆盖符号链接形式的 Hook')
    return path.resolve()


def install_post_commit_hook(project_root):
    root = Path(project_root).resolve()
    path = hook_path(root)
    manifest_path = metadata_path(root, 'hook-install.json')
    manifest = read_json(manifest_path)
    if manifest:
        if path.exists() and hashlib.sha256(path.read_bytes()).hexdigest() == manifest['installed_hash']:
            return True
        raise ValueError('已安装 Hook 被外部修改，请先合并，禁止覆盖')
    previous = path.with_name('post-commit.ide-audit.previous')
    if previous.exists():
        raise ValueError('Hook 备份已存在，禁止覆盖')
    old = path.read_bytes() if path.exists() else None
    old_mode = path.stat().st_mode if path.exists() else None
    if old is not None:
        previous.write_bytes(old)
        previous.chmod(old_mode)
    content = '#!/bin/sh\n# IDE_AUDIT_MANAGED\n'
    if old is not None:
        content += f'{shlex.quote(previous.as_posix())} "$@"\nprevious_status=$?\n'
    else:
        content += 'previous_status=0\n'
    content += (f'{shlex.quote(Path(sys.executable).as_posix())} -m archguard.cli.main '
                f'--project-root {shlex.quote(root.as_posix())} audit --notify\n'
                'audit_status=$?\n'
                'if [ "$audit_status" -ne 0 ]; then echo "IDE_Audit: audit failed; retry with archguard audit" >&2; fi\n'
                'if [ "$previous_status" -ne 0 ]; then exit "$previous_status"; fi\nexit "$audit_status"\n')
    atomic_text(path, content)
    path.chmod(path.stat().st_mode | stat.S_IEXEC)
    atomic_json(manifest_path, {'path': str(path), 'previous': str(previous) if old is not None else None,
                               'installed_hash': hashlib.sha256(path.read_bytes()).hexdigest()})
    return True


def uninstall_post_commit_hook(project_root):
    manifest_path = metadata_path(project_root, 'hook-install.json')
    manifest = read_json(manifest_path)
    if not manifest:
        return True
    path = hook_path(project_root)
    if str(path) != manifest['path'] or not path.exists() or hashlib.sha256(path.read_bytes()).hexdigest() != manifest['installed_hash']:
        raise ValueError('Hook 已变更，不能自动卸载')
    previous = path.with_name('post-commit.ide-audit.previous')
    if manifest['previous']:
        if str(previous) != manifest['previous'] or not previous.exists():
            raise ValueError('缺少原 Hook 备份')
        path.write_bytes(previous.read_bytes())
        path.chmod(previous.stat().st_mode)
        previous.unlink()
    else:
        path.unlink()
    manifest_path.unlink()
    return True
