"""prompt_store 单元测试

验证：
- 多条 prompt 追加写入
- 归档与清空机制
- 空 pending 读取与边界处理
"""

import json
from pathlib import Path

import pytest

from archguard.core.prompt_store import (
    archive_and_clear,
    get_pending_prompts,
    record_prompt,
)


@pytest.fixture
def project_root(tmp_path: Path) -> Path:
    """创建临时项目根目录"""
    return tmp_path


class TestRecordPrompt:
    """测试 prompt 追加记录"""

    def test_record_single_prompt(self, project_root: Path) -> None:
        """单条 prompt 写入后可读取"""
        record_prompt(project_root, "添加日志功能")
        prompts = get_pending_prompts(project_root)
        assert len(prompts) == 1
        assert prompts[0]["text"] == "添加日志功能"
        assert "timestamp" in prompts[0]

    def test_record_multiple_prompts(self, project_root: Path) -> None:
        """多条 prompt 按追加顺序保留"""
        record_prompt(project_root, "第一条需求")
        record_prompt(project_root, "第二条需求")
        record_prompt(project_root, "第三条需求")
        prompts = get_pending_prompts(project_root)
        assert len(prompts) == 3
        assert prompts[0]["text"] == "第一条需求"
        assert prompts[1]["text"] == "第二条需求"
        assert prompts[2]["text"] == "第三条需求"

    def test_record_empty_text_raises(self, project_root: Path) -> None:
        """空文本应抛出异常"""
        with pytest.raises(ValueError):
            record_prompt(project_root, "")
        with pytest.raises(ValueError):
            record_prompt(project_root, "   ")


class TestGetPending:
    """测试 pending prompts 读取"""

    def test_empty_pending(self, project_root: Path) -> None:
        """无 pending 时返回空列表"""
        prompts = get_pending_prompts(project_root)
        assert prompts == []


class TestArchiveAndClear:
    """测试归档与清空"""

    def test_archive_clears_pending(self, project_root: Path) -> None:
        """归档后 pending 被清空"""
        record_prompt(project_root, "需求A")
        record_prompt(project_root, "需求B")
        archive_path = archive_and_clear(project_root, "abc1234567890")
        assert archive_path is not None
        # pending 应该为空
        assert get_pending_prompts(project_root) == []
        # 归档文件应该存在且包含原始数据
        with open(archive_path, "r", encoding="utf-8") as f:
            archived = json.load(f)
        assert len(archived) == 2
        assert archived[0]["text"] == "需求A"

    def test_archive_empty_pending(self, project_root: Path) -> None:
        """空 pending 归档返回 None"""
        result = archive_and_clear(project_root, "abc1234")
        assert result is None
