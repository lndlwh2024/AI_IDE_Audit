"""审计元数据的路径约束、进程锁和原子文件替换。"""
import json
import os
import time
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4


def metadata_path(root, *parts):
    project = Path(root).resolve()
    base = project / '.ide_audit'
    if base.is_symlink() or (base.exists() and base.resolve() != base):
        raise ValueError('审计目录不能重定向到其他位置')
    path = base.joinpath(*parts)
    # 先验证词法边界，再逐级拒绝链接；不解析其他线程正在创建或锁定的文件。
    if '..' in path.parts or not path.is_relative_to(base):
        raise ValueError('元数据路径超出审计目录')
    candidate = base
    for part in path.relative_to(base).parts:
        candidate = candidate / part
        if candidate.is_symlink() or (hasattr(candidate, 'is_junction') and candidate.is_junction()):
            raise ValueError('元数据路径不能包含链接')
    return path


def read_json(path, default=None):
    path = Path(path)
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding='utf-8'))


def atomic_text(path, text):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + '.' + uuid4().hex + '.tmp')
    try:
        with temp.open('x', encoding='utf-8', newline='\n') as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def atomic_json(path, value):
    atomic_text(path, json.dumps(value, ensure_ascii=False, indent=2) + '\n')


@contextmanager
def transaction(root, name='state', timeout=15):
    """锁文件保留原位；OS 锁随进程退出释放，不以时间删除仍在使用的锁。"""
    if not name or any(c not in 'abcdefghijklmnopqrstuvwxyz0123456789-_' for c in name):
        raise ValueError('非法事务锁名称')
    path = metadata_path(root, 'locks', name + '.lock')
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a+b') as stream:
        stream.seek(0, 2)
        if stream.tell() == 0:
            stream.write(b'0')
            stream.flush()
        deadline = time.monotonic() + timeout
        while True:
            try:
                stream.seek(0)
                if os.name == 'nt':
                    import msvcrt
                    msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError:
                if time.monotonic() >= deadline:
                    raise TimeoutError(f'等待事务锁超时: {name}')
                time.sleep(0.025)
        try:
            yield
        finally:
            stream.seek(0)
            if os.name == 'nt':
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
