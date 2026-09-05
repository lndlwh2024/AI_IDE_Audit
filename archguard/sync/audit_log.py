import logging
from pathlib import Path
from .schemas import LedgerEvent

logger = logging.getLogger(__name__)

class AuditLogManager:
    """
    为了方便人类开发者和没有严格 Schema 解析能力的模型，提供明文维度的项目状态及日志追加支持。
    """
    def __init__(self, project_root: Path):
        self.collab_dir = Path(project_root) / '.ide_audit' / 'collab'
        self.audit_file = self.collab_dir / 'AUDIT_LOG.md'
        self.state_file = self.collab_dir / 'PROJECT_STATE.md'
        self.collab_dir.mkdir(parents=True, exist_ok=True)

    def append_audit_log(self, event: LedgerEvent):
        """
        追加符合规范的 Markdown 列表条目。
        由于 dual-agent-sync 中的样式为简明标题+核心细节，这里尽量一致化呈现。
        """
        files_affected = [fc.file for fc in event.scope.files_changed] if event.scope.files_changed else []
        files_str = ", ".join(files_affected) if files_affected else "None"
        
        md_entry = f"""
## {event.timestamp} - {event.version} - {event.source_ai_ide}
- Project: {event.project}
- Type: {event.event_type}
- Summary: {event.summary}
- Files: {files_str}
"""
        with open(self.audit_file, 'a', encoding='utf-8') as f:
            f.write(md_entry)
            
    def update_project_state(self, content: str):
        """
        更新宏观的项目状态，该文件为全局单例，每次更新都会覆盖写入。
        """
        self.state_file.write_text(content, encoding='utf-8')
