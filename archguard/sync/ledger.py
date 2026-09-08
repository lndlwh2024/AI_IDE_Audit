"""追加式账本：在进程锁内验证历史、分配版本、持久追加。"""
import os
import json
from pathlib import Path
from archguard.storage import metadata_path, transaction, atomic_text
from .schemas import LedgerEvent


class LedgerManager:
    def __init__(self, project_root):
        self.project_root = Path(project_root).resolve()
        self.ledger_file = metadata_path(project_root, 'collab', 'ledger.jsonl')

    def read_all_events(self):
        if not self.ledger_file.exists():
            return []
        content = self.ledger_file.read_text(encoding='utf-8')
        if content and not content.endswith('\n'):
            raise ValueError('账本最后一行不完整，须恢复后继续写入')
        events = []
        for i, line in enumerate(content.splitlines(), 1):
            event = LedgerEvent.model_validate_json(line)
            if event.version != f'v{i:04d}':
                raise ValueError(f'账本第 {i} 行版本不连续')
            events.append(event)
        return events

    def get_latest_version(self):
        events = self.read_all_events()
        return events[-1].version if events else 'v0000'

    def append_event(self, event_data):
        with transaction(self.project_root, 'ledger'):
            events = self.read_all_events()
            payload = dict(event_data, version=f'v{len(events) + 1:04d}')
            event = LedgerEvent.model_validate(payload)
            self.ledger_file.parent.mkdir(parents=True, exist_ok=True)
            with self.ledger_file.open('a', encoding='utf-8', newline='\n') as stream:
                stream.write(event.model_dump_json(by_alias=True) + '\n')
                stream.flush()
                os.fsync(stream.fileno())
            self._rebuild_views(events + [event])
            return event

    def _rebuild_views(self, events):
        """派生视图可由账本重建；重试不会重复追加 Markdown。"""
        log = '# 协同事件流水\n\n' + '\n'.join(
            f'## {e.version} · {e.source_ai_ide} · {e.event_type}\n\n{e.timestamp}\n\n{e.summary}\n\n'
            + '影响文件：' + '、'.join([f.file for f in e.scope.files_changed] + e.scope.docs_changed) + '\n\n'
            + '```json\n' + json.dumps({'context': e.context.model_dump(mode='json'),
                                       'verification': e.verification.model_dump(mode='json'),
                                       'graph_impact': e.graph_impact.model_dump(mode='json')}, ensure_ascii=False, indent=2)
            + '\n```\n' for e in events)
        atomic_text(self.ledger_file.parent / 'AUDIT_LOG.md', log)
        if events:
            last = events[-1]
            corrected = {e.context.diagnostic_record.supersedes_version for e in events
                         if e.context.diagnostic_record and e.context.diagnostic_record.status == 'corrected'}
            active = [{'version': e.version, 'source_ai_ide': e.source_ai_ide,
                       'diagnostic_record': e.context.diagnostic_record.model_dump(mode='json')}
                      for e in events if e.context.diagnostic_record and e.version not in corrected]
            atomic_text(self.ledger_file.parent / 'PROJECT_STATE.md',
                        f'# 项目状态 · {last.version}\n\n{last.context.current_status}\n\n' +
                        '## 下一步\n\n' + '\n'.join('- ' + x for x in last.context.next_steps) + '\n\n'
                        + '## 未解决问题与风险\n\n' + '\n'.join('- ' + x for x in last.context.remaining_issues + last.context.risks)
                        + '\n\n## 当前有效诊断\n\n```json\n' + json.dumps(active, ensure_ascii=False, indent=2) + '\n```\n')

    def rebuild_views(self):
        with transaction(self.project_root, 'ledger'):
            self._rebuild_views(self.read_all_events())

    def read_events_from_line(self, start_line):
        if start_line < 1:
            raise ValueError('行号必须大于零')
        return self.read_all_events()[start_line - 1:]

    def validate_event(self, event):
        try:
            LedgerEvent.model_validate(event.model_dump(by_alias=True))
            return True
        except ValueError:
            return False
