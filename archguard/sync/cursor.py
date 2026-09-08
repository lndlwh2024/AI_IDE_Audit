"""会话游标的进程内/进程间安全合并与增量校验。"""
import re
from datetime import datetime, timezone
from archguard.storage import metadata_path, read_json, atomic_json, transaction
from .schemas import CursorFile, CursorSession
from .ledger import LedgerManager


def valid_id(ide_id):
    if not re.fullmatch('[a-z0-9-]+', ide_id):
        raise ValueError('IDE 标识仅支持小写字母、数字、连字符')
    return ide_id


class CursorManager:
    def __init__(self, project_root):
        self.root = project_root
        self.cursors_dir = metadata_path(project_root, 'collab', 'cursors')
        self.ledger = LedgerManager(project_root)

    def read_cursor(self, ide_id):
        path = metadata_path(self.root, 'collab', 'cursors', valid_id(ide_id) + '.json')
        data = read_json(path)
        if data is None:
            return CursorFile(ai_ide_id=ide_id, sessions={})
        if 'sessions' not in data:
            # V1 平面游标保持原记录文件，当前新会话必须全量读取。
            return CursorFile(ai_ide_id=ide_id, sessions={})
        cursor = CursorFile.model_validate(data)
        if cursor.ai_ide_id != ide_id:
            raise ValueError('游标文件与 IDE 身份不一致')
        return cursor

    def start_session(self, ide_id):
        valid_id(ide_id)
        with transaction(self.root, 'cursor-' + ide_id):
            cursor = self.read_cursor(ide_id)
            prefix = ide_id.upper() + '_' + datetime.now().strftime('%Y%m%d%H%M') + '_'
            used = [s[len(prefix):] for s in cursor.sessions if s.startswith(prefix)]
            for sequence in range(26 * 9999):
                suffix = chr(65 + sequence // 9999) + f'{sequence % 9999 + 1:04d}'
                if suffix not in used:
                    session_id = prefix + suffix
                    break
            else:
                raise ValueError('本分钟会话编号已耗尽')
            cursor.sessions[session_id] = CursorSession(last_read_version='v0000', last_read_line=0)
            atomic_json(self.cursors_dir / (ide_id + '.json'), cursor.model_dump())
            return session_id

    def update_cursor(self, ide_id, session_id, version, line):
        valid_id(ide_id)
        if line < 0 or version != f'v{line:04d}':
            raise ValueError('版本与行号不一致')
        with transaction(self.root, 'cursor-' + ide_id):
            cursor = self.read_cursor(ide_id)
            cursor.sessions[session_id] = CursorSession(last_read_version=version, last_read_line=line,
                last_read_timestamp=datetime.now(timezone.utc).isoformat())
            atomic_json(self.cursors_dir / (ide_id + '.json'), cursor.model_dump())

    def get_unread_events(self, ide_id, session_id):
        cursor = self.read_cursor(ide_id)
        session = cursor.sessions.get(session_id)
        events = self.ledger.read_all_events()
        line = session.last_read_line if session else None
        if line is None or line > len(events) or line < 0:
            line = 0
        elif line and events[line - 1].version != session.last_read_version:
            line = 0
        return events[line:], len(events)
