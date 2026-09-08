"""开发端需求记录；为每条原文绑定记录时的基线提交。"""
from datetime import datetime, timezone
from uuid import uuid4
import git
from archguard.storage import metadata_path, read_json, atomic_json, transaction


def get_pending_prompts(project_root):
    value = read_json(metadata_path(project_root, 'prompts', 'pending.json'), [])
    if not isinstance(value, list):
        raise ValueError('pending.json 必须是列表，禁止默默覆盖异常数据')
    return value


def record_prompt(project_root, text):
    if not text or not text.strip():
        raise ValueError('需求文本不能为空')
    try:
        base = git.Repo(project_root).head.commit.hexsha
    except (git.InvalidGitRepositoryError, ValueError):
        base = None
    entry = {'id': uuid4().hex, 'text': text, 'timestamp': datetime.now(timezone.utc).isoformat(), 'base_commit': base}
    with transaction(project_root):
        pending = get_pending_prompts(project_root)
        pending.append(entry)
        atomic_json(metadata_path(project_root, 'prompts', 'pending.json'), pending)
    return entry


def archive_and_clear(project_root, commit_hash):
    """旧开发端显式归档接口；审计查询不调用此接口。"""
    import re
    if not re.fullmatch('[a-zA-Z0-9_-]+', commit_hash):
        raise ValueError('非法归档标识')
    with transaction(project_root):
        pending = get_pending_prompts(project_root)
        if not pending:
            return None
        path = metadata_path(project_root, 'prompts', 'archived', uuid4().hex + '_' + commit_hash[:7] + '.json')
        atomic_json(path, pending)
        atomic_json(metadata_path(project_root, 'prompts', 'pending.json'), [])
        return str(path)
