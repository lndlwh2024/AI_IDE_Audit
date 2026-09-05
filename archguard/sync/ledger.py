import logging
from pathlib import Path
from typing import List
from .schemas import LedgerEvent

logger = logging.getLogger(__name__)

class LedgerManager:
    """
    负责对 `collab/ledger.jsonl` 进行追加写入、行级读取和完整性验证。
    """
    def __init__(self, project_root: Path):
        self.ledger_file = Path(project_root) / '.ide_audit' / 'collab' / 'ledger.jsonl'
        self.ledger_file.parent.mkdir(parents=True, exist_ok=True)
        
    def get_latest_version(self) -> str:
        """获取最新事件的版本号"""
        if not self.ledger_file.exists():
            return "v0000"
        
        last_line = None
        with open(self.ledger_file, 'r', encoding='utf-8') as f:
            for line in f:
                if line.strip():
                    last_line = line
        
        if last_line:
            try:
                event = LedgerEvent.model_validate_json(last_line)
                return event.version
            except Exception:
                pass
        return "v0000"

    def append_event(self, event_data: dict) -> LedgerEvent:
        """
        追加事件到 ledger.jsonl，自动计算并填充下一个版本号，严格按序递增（不跳号）。
        行号 N 必定对应 v{N:04d}。
        """
        latest = self.get_latest_version()
        next_num = int(latest[1:]) + 1
        new_version = f"v{next_num:04d}"
        
        event_data['version'] = new_version
        
        # Pydantic v2 会在此处进行 schema 自动校验
        event = LedgerEvent.model_validate(event_data)
        
        with open(self.ledger_file, 'a', encoding='utf-8') as f:
            f.write(event.model_dump_json(by_alias=True) + "\n")
            
        logger.info(f"追加事件成功，分配版本号: {new_version}")
        return event

    def read_all_events(self) -> List[LedgerEvent]:
        """全量读取并反序列化所有的事件"""
        events = []
        if not self.ledger_file.exists():
            return events
            
        with open(self.ledger_file, 'r', encoding='utf-8') as f:
            for line in f:
                if line.strip():
                    events.append(LedgerEvent.model_validate_json(line))
        return events

    def read_events_from_line(self, start_line: int) -> List[LedgerEvent]:
        """从指定行号（从1开始计数）增量读取后续所有事件。"""
        events = []
        if not self.ledger_file.exists():
            return events
            
        with open(self.ledger_file, 'r', encoding='utf-8') as f:
            for i, line in enumerate(f, 1):
                if i >= start_line and line.strip():
                    events.append(LedgerEvent.model_validate_json(line))
        return events

    def validate_event(self, event: LedgerEvent) -> bool:
        """校验事件格式完整性 (其实在使用 Pydantic 实例化时已经保证，此处为显式接口)"""
        try:
            LedgerEvent.model_validate(event.model_dump(by_alias=True))
            return True
        except Exception as e:
            logger.error(f"事件校验失败: {e}")
            return False
