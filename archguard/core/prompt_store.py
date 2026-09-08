"""历史模块的只读需求入口。写入接口已移到 archguard.sync.prompts。"""
from archguard.storage import metadata_path, read_json


def get_pending_prompts(project_root):
    value = read_json(metadata_path(project_root, 'prompts', 'pending.json'), [])
    if not isinstance(value, list):
        raise ValueError('需求存储格式错误')
    return value
