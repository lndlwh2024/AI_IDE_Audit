"""只记录计量元数据，不保存提示词、源码或工具正文。"""
import json
import time
import warnings
from uuid import uuid4
from archguard.storage import metadata_path, atomic_json, read_json


def size(value):
    text = json.dumps(value, ensure_ascii=False, default=str, separators=(',', ':'))
    return {'characters': len(text), 'utf8_bytes': len(text.encode('utf-8'))}


def write(root, operation, **metadata):
    # 日志失败不能把已成功的记账伪装成失败，诱发业务重试。
    try:
        identifier = f'{time.time_ns():020d}-{uuid4().hex}'
        atomic_json(metadata_path(root, 'operation-usage', identifier + '.json'),
                    {'id': identifier, 'time': time.time(), 'operation': operation, **metadata})
    except Exception as exc:
        warnings.warn(f'用量日志保存失败：{type(exc).__name__}', RuntimeWarning)


def read(root, limit=10, before=None):
    if not 1 <= limit <= 20:
        raise ValueError('日志每页限制为 1 到 20 条')
    paths = sorted(metadata_path(root, 'operation-usage').glob('*.json'), reverse=True)
    paths = [p for p in paths if before is None or p.stem < before]
    selected = paths[:limit]
    return {'records': [read_json(p) for p in selected],
            'next_before': selected[-1].stem if len(paths) > limit else None,
            'note': '工具数据大小不是总 token；实际用量见 phase_finished / b_audit_finished。区间不能相加冒充独占消耗；日志不含源码正文。'}
