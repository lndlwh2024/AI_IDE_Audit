import re
from datetime import datetime
from typing import Optional

def validate_ai_ide_id(ide_id: str) -> bool:
    """
    校验 AI IDE ID 格式。
    必须是小写英文、数字或连字符，避免特殊字符导致路径问题。
    """
    return bool(re.match(r'^[a-z0-9\-]+$', ide_id))

def generate_session_id(ide_id: str, last_session_id: Optional[str] = None) -> str:
    """
    自动生成会话 ID。
    格式要求: <IDE大写>_<YYYYMMDDHHmm>_<字母><4位数字>
    例如: TRAE_202607091800_A0001
    """
    now = datetime.now()
    timestamp = now.strftime('%Y%m%d%H%M')
    prefix = f"{ide_id.upper()}_{timestamp}_"
    
    # 按照规则递增序号 (A0001 -> A9999 -> B0001 ...)
    if last_session_id and last_session_id.startswith(prefix):
        seq_part = last_session_id.split('_')[-1]
        if len(seq_part) == 5:
            letter = seq_part[0]
            try:
                num = int(seq_part[1:])
                num += 1
                if num > 9999:
                    num = 1
                    letter = chr(ord(letter) + 1)
                    if letter > 'Z':
                        letter = 'A' # 回滚或异常处理，此处简单轮转
                return f"{prefix}{letter}{num:04d}"
            except ValueError:
                pass
                
    # 如果前缀不匹配，即时间戳变了，或无历史记录，从 A0001 开始
    return f"{prefix}A0001"
