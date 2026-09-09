"""事件与图谱的一次性可恢复交接；重试使用固定候选图，不重复记账。"""
import hashlib
import json
import re
from archguard.storage import metadata_path, read_json, atomic_json, transaction
from .ledger import LedgerManager
from .cursor import CursorManager
from .graph import GraphManager
from .schemas import LedgerEvent, CodeGraph


class SyncWorkflow:
    def __init__(self, root):
        self.root = root
        self.pending = metadata_path(root, 'workflow', 'pending.json')

    def recover(self):
        record = read_json(self.pending)
        if not record:
            return None
        ledger = LedgerManager(self.root)
        try:
            events = ledger.read_all_events()
        except (ValueError, UnicodeError):
            # 只修复本事务的已验证追加尾部，不截断无法归属的历史损坏。
            with transaction(self.root, 'ledger'):
                data = ledger.ledger_file.read_bytes()
                prefix = data[:record['ledger_size']]
                tail = data[record['ledger_size']:]
                expected = LedgerEvent.model_validate(dict(record['event'], operation_id=record['id'])).model_dump_json(by_alias=True).encode() + b'\n'
                if (len(prefix) != record['ledger_size'] or hashlib.sha256(prefix).hexdigest() != record['ledger_hash']
                        or not expected.startswith(tail)):
                    raise ValueError('账本损坏不属于当前事务，不能自动修复')
                with ledger.ledger_file.open('r+b') as stream:
                    stream.truncate(record['ledger_size'])
            events = ledger.read_all_events()
        event = next((e for e in events if getattr(e, 'operation_id', None) == record['id']), None)
        if event is None:
            event = ledger.append_event(dict(record['event'], operation_id=record['id']))
        else:
            ledger.rebuild_views()
        graph = GraphManager(self.root)
        with transaction(self.root, 'graph'):
            graph._recover()
            current = graph.read_graph()
            if getattr(current.meta, 'operation_id', None) != record['id']:
                candidate = CodeGraph.model_validate(record['graph'])
                candidate.meta.operation_id = record['id']
                graph._commit(current, candidate, event.source_ai_ide, event.version, record['cache'])
        if record.get('session_id'):
            cursors = CursorManager(self.root)
            session = cursors.read_cursor(event.source_ai_ide).sessions[record['session_id']]
            # 只有旧事件全部已读时才推进到本操作；不能替用户跳过其他事件。
            if session.last_read_line == record['ledger_count']:
                cursors.update_cursor(event.source_ai_ide, record['session_id'], event.version, int(event.version[1:]))
        result = {'operation_id': record['id'], 'event_version': event.version,
                  'graph_version': graph.read_graph().meta.version, 'status': 'completed', 'input_hash': record['hash']}
        atomic_json(metadata_path(self.root, 'workflow', 'completed', record['id'] + '.json'), result)
        self.pending.unlink()
        return result

    def complete(self, operation_id, event_data, session_id=None):
        if not re.fullmatch('[a-zA-Z0-9_-]{1,100}', operation_id):
            raise ValueError('非法操作 ID')
        payload = LedgerEvent.model_validate(dict(event_data, version='v0000')).model_dump(mode='json', by_alias=True)
        digest = hashlib.sha256(json.dumps({'event': payload, 'session_id': session_id}, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        with transaction(self.root, 'workflow'):
            self.recover()
            saved = read_json(metadata_path(self.root, 'workflow', 'completed', operation_id + '.json'))
            if saved:
                if saved['input_hash'] != digest:
                    raise ValueError('同一操作 ID 不得用于不同事件')
                return saved
            if session_id and session_id not in CursorManager(self.root).read_cursor(payload['source_ai_ide']).sessions:
                raise ValueError('协同会话不存在')
            ledger = LedgerManager(self.root)
            events = ledger.read_all_events()
            ledger_bytes = ledger.ledger_file.read_bytes() if ledger.ledger_file.exists() else b''
            payload['version'] = f'v{len(events) + 1:04d}'
            graph = GraphManager(self.root)
            with transaction(self.root, 'graph'):
                graph._recover()
                _, candidate, cache = graph.preview()
            atomic_json(self.pending, {'id': operation_id, 'hash': digest, 'event': payload,
                                      'session_id': session_id, 'ledger_count': len(events),
                                      'ledger_size': len(ledger_bytes), 'ledger_hash': hashlib.sha256(ledger_bytes).hexdigest(),
                                      'graph': candidate.model_dump(mode='json', by_alias=True), 'cache': cache})
            return self.recover()
