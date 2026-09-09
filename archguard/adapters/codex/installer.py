"""项目级安装：幂等管理自己的配置与守则块，保留用户已有内容。"""
import json
import sys
import tomllib
from pathlib import Path
import git
from archguard.storage import metadata_path, atomic_text, atomic_json, read_json, transaction
from archguard.config.settings import ensure_directories
from archguard.adapters.git_hook import install_post_commit_hook, uninstall_post_commit_hook

START = '# BEGIN IDE_AUDIT'
END = '# END IDE_AUDIT'


def managed_text(original, body):
    if START in original or END in original:
        if original.count(START) != 1 or original.count(END) != 1:
            raise ValueError('IDE_Audit 配置标记不完整')
        start, end = original.index(START), original.index(END) + len(END)
        if end < start:
            raise ValueError('配置标记顺序错误')
        original = original[:start] + original[end:].lstrip('\n')
    return original.rstrip() + ('\n\n' if original.strip() else '') + (START + '\n' + body.rstrip() + '\n' + END + '\n' if body else '')


def install_to_project(project_root, ide='codex-desktop'):
    if ide not in ('codex', 'codex-desktop'):
        raise ValueError('当前仅支持 Codex 桌面版')
    root = Path(project_root).resolve()
    git.Repo(root)
    config = root / '.codex' / 'config.toml'
    agents = root / 'AGENTS.md'
    for target in (config, agents):
        if target.is_symlink() or not target.parent.resolve().is_relative_to(root):
            raise ValueError('安装目标不能通过链接重定向到工程外')
    config_existed, agents_existed = config.exists(), agents.exists()
    old_config = config.read_text(encoding='utf-8') if config.exists() else ''
    old_agents = agents.read_text(encoding='utf-8') if agents.exists() else ''
    parsed = tomllib.loads(old_config)
    if 'ide_audit_dev' in parsed.get('mcp_servers', {}) and START not in old_config:
        raise ValueError('已有同名 MCP 配置不归本插件管理')
    body = '[mcp_servers.ide_audit_dev]\ncommand = ' + json.dumps(sys.executable) + '\nargs = ' + json.dumps(
        ['-m', 'archguard.mcp.server', '--project-root', str(root), '--role', 'dev']) + '\n'
    new_config = managed_text(old_config, body)
    tomllib.loads(new_config)
    template = (Path(__file__).parents[2] / 'templates' / 'skill_codex_dev.md').read_text(encoding='utf-8')
    new_agents = managed_text(old_agents, template)
    with transaction(root, 'install'):
        ensure_directories(root)
        backup = metadata_path(root, 'install-backup.json')
        if not backup.exists():
            atomic_json(backup, {'config': old_config, 'agents': old_agents})
        try:
            atomic_text(config, new_config)
            atomic_text(agents, new_agents)
            install_post_commit_hook(root)
        except Exception:
            if config_existed:
                atomic_text(config, old_config)
            else:
                config.unlink(missing_ok=True)
            if agents_existed:
                atomic_text(agents, old_agents)
            else:
                agents.unlink(missing_ok=True)
            raise
    return {'project_root': str(root), 'config': str(config), 'status': 'installed'}


def uninstall_from_project(project_root):
    root = Path(project_root).resolve()
    with transaction(root, 'install'):
        config = root / '.codex/config.toml'
        agents = root / 'AGENTS.md'
        planned = {}
        for path in (config, agents):
            if path.exists():
                planned[path] = managed_text(path.read_text(encoding='utf-8'), '')
        uninstall_post_commit_hook(root)
        for path, value in planned.items():
            atomic_text(path, value)
    return {'status': 'uninstalled', 'retained': '.ide_audit 审计及协同历史'}
