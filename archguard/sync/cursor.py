import logging
from pathlib import Path
from typing import List, Tuple
from datetime import datetime
from .schemas import CursorFile, CursorSession, LedgerEvent
from .ledger import LedgerManager

logger = logging.getLogger(__name__)

class CursorManager:
    """
    负责维护不同 AI IDE 读者的游标信息，精确记录各个独立会话（per-session）的消费进度。
    """
    def __init__(self, project_root: Path):
        self.cursors_dir = Path(project_root) / '.ide_audit' / 'collab' / 'cursors'
        self.cursors_dir.mkdir(parents=True, exist_ok=True)
        self.ledger = LedgerManager(project_root)

    def read_cursor(self, ide_id: str) -> CursorFile:
        """读取指定 AI IDE 的全量游标文件"""
        cursor_path = self.cursors_dir / f"{ide_id}.json"
        if not cursor_path.exists():
            return CursorFile(ai_ide_id=ide_id, sessions={})
            
        try:
            content = cursor_path.read_text(encoding='utf-8')
            return CursorFile.model_validate_json(content)
        except Exception as e:
            logger.warning(f"无法读取或解析游标 {ide_id}: {e}，将返回空游标状态")
            return CursorFile(ai_ide_id=ide_id, sessions={})

    def update_cursor(self, ide_id: str, session_id: str, version: str, line: int):
        """
        更新特定会话读取位置。
        调用前需要结合 LockManager，确保写入时的并发一致性（读-合-写）。
        """
        cursor = self.read_cursor(ide_id)
        if session_id not in cursor.sessions:
            cursor.sessions[session_id] = CursorSession(last_read_version="v0000")
            
        session = cursor.sessions[session_id]
        session.last_read_version = version
        session.last_read_line = line
        session.last_read_timestamp = datetime.now().isoformat()
        
        cursor_path = self.cursors_dir / f"{ide_id}.json"
        cursor_path.write_text(cursor.model_dump_json(indent=2), encoding='utf-8')
        logger.info(f"游标进度更新成功: IDE={ide_id}, Session={session_id}, Version={version}")

    def get_unread_events(self, ide_id: str, session_id: str) -> Tuple[List[LedgerEvent], int]:
        """
        基于游标位置读取未读事件。
        如果在增量读取过程中发现行号与版本不一致，会自动退回至全量读取模式以保证数据一致性。
        返回: (事件列表, 最新行号)
        """
        cursor = self.read_cursor(ide_id)
        last_line = cursor.sessions.get(session_id, CursorSession(last_read_version="v0000")).last_read_line
        
        start_line = (last_line + 1) if last_line else 1
        events = self.ledger.read_events_from_line(start_line)
        
        # 严格校验：第一条获取的事件的 version 必须满足预期 v{start_line:04d}
        if events:
            expected_version = f"v{start_line:04d}"
            if events[0].version != expected_version:
                logger.warning(
                    f"行号校验失败。预期第一条是 {expected_version} 但实际读取到 {events[0].version}。"
                    "可能因为 ledger 曾被手动修剪，退回全量读取模式处理。"
                )
                events = self.ledger.read_all_events()
                start_line = 1
                
        new_line = (start_line - 1) + len(events)
        return events, new_line
