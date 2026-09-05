import json
import logging
import httpx
from pathlib import Path
from typing import Optional, Dict, Any
from archguard.config.settings import get_ide_audit_dir

logger = logging.getLogger(__name__)

class CodexSessionManager:
    """Codex B窗口会话管理器"""
    
    def __init__(self, project_root: str):
        self.project_root = project_root
        self.session_file = Path(get_ide_audit_dir(project_root)) / "session.json"
        self.api_base = "http://localhost:3000/api" # 假设的 API 地址
        
    def _save_thread_id(self, thread_id: str):
        """持久化 threadId"""
        self.session_file.write_text(json.dumps({"thread_id": thread_id}))
        
    def _get_thread_id(self) -> Optional[str]:
        """获取 threadId"""
        if self.session_file.exists():
            try:
                data = json.loads(self.session_file.read_text())
                return data.get("thread_id")
            except Exception:
                return None
        return None

    def create_audit_session(self) -> str:
        """创建新的审计会话"""
        logger.info("创建新的审计会话")
        # 模拟 API 调用
        thread_id = "new_thread_id_123"
        self._save_thread_id(thread_id)
        return thread_id
        
    def resume_audit_session(self, thread_id: str) -> bool:
        """复用已有会话"""
        logger.info(f"复用会话: {thread_id}")
        return True

    def send_audit_task(self, thread_id: str, report_data: Dict[str, Any]) -> bool:
        """发送审计任务"""
        logger.info(f"向会话 {thread_id} 发送审计任务")
        try:
            # 模拟使用 httpx 发送
            # httpx.post(f"{self.api_base}/thread/{thread_id}/message", json=report_data)
            return True
        except Exception as e:
            logger.error(f"发送审计任务失败: {e}")
            return False
