"""审计主引擎端到端测试

创建临时 Git 仓库 → 写入 prompt → 执行 commit → 运行引擎 → 验证输出。
"""

import json
from pathlib import Path

import git
import pytest

from archguard.core.engine import run_audit
from archguard.core.prompt_store import record_prompt


@pytest.fixture
def project_with_commit(tmp_path: Path) -> Path:
    """创建一个有两次 commit 的临时项目

    第一次 commit：初始化项目
    第二次 commit：新增一个 migration 文件（应触发架构信号）
    """
    # 初始化独立的临时 Git 仓库，避免污染宿主环境
    repo = git.Repo.init(tmp_path)
    repo.config_writer().set_value("user", "name", "test").release()
    repo.config_writer().set_value("user", "email", "test@test.com").release()

    # 第一次 commit：建立基线提交
    readme = tmp_path / "README.md"
    readme.write_text("# Test\n")
    repo.index.add(["README.md"])
    repo.index.commit("Initial commit")

    # 记录用户需求（模拟两次 commit 之间的用户输入记录）
    record_prompt(tmp_path, "添加用户表的数据库迁移")
    record_prompt(tmp_path, "请同时更新 README")

    # 第二次 commit：新增 migration + 更新 README，构造触发架构信号的场景
    migrations_dir = tmp_path / "app" / "migrations"
    migrations_dir.mkdir(parents=True)
    migration_file = migrations_dir / "0001_create_users.py"
    migration_file.write_text('"""Create users table"""\n')
    readme.write_text("# Test\n\nUpdated\n")
    repo.index.add(["app/migrations/0001_create_users.py", "README.md"])
    repo.index.commit("Add user migration and update readme")

    return tmp_path


class TestRunAudit:
    """测试审计主引擎"""

    def test_full_audit_flow(self, project_with_commit: Path) -> None:
        """端到端：运行完整审计流程并验证结果结构与业务字段"""
        result = run_audit(project_with_commit)

        # 基本结构验证
        assert result.commit_hash
        assert result.timestamp
        assert result.commit_message == "Add user migration and update readme"

        # 用户需求应被正确捕获
        assert len(result.prompts) == 2
        assert result.prompts[0]["text"] == "添加用户表的数据库迁移"
        assert result.prompts[1]["text"] == "请同时更新 README"

        # Diff 摘要验证
        assert result.diff_summary["total_files_changed"] == 2

        # 架构信号验证：应至少检测到 migration 文件的信号
        signal_ids = [s["rule_id"] for s in result.architecture_signals]
        assert "DB_MIGRATION_FILE" in signal_ids

        # 信号汇总验证
        assert result.signal_summary["total"] >= 1

    def test_result_saved_to_files(self, project_with_commit: Path) -> None:
        """审计结果应持久化到 latest.json 和历史归档"""
        run_audit(project_with_commit)

        # latest.json 应存在且内容符合预期
        latest = project_with_commit / ".ide_audit" / "results" / "latest.json"
        assert latest.exists()
        with open(latest, "r", encoding="utf-8") as f:
            data = json.load(f)
        assert "commit_hash" in data
        assert "architecture_signals" in data

        # 历史归档目录应存在且包含快照文件
        history_dir = project_with_commit / ".ide_audit" / "results" / "history"
        assert any(history_dir.iterdir())

    def test_pending_cleared_after_audit(self, project_with_commit: Path) -> None:
        """审计完成后 pending prompts 应被清空，避免跨周期污染"""
        from archguard.core.prompt_store import get_pending_prompts

        run_audit(project_with_commit)
        pending = get_pending_prompts(project_with_commit)
        assert pending == []

    def test_prompts_archived(self, project_with_commit: Path) -> None:
        """审计完成后 prompts 应被归档保存"""
        run_audit(project_with_commit)
        archive_dir = project_with_commit / ".ide_audit" / "prompts" / "archived"
        assert archive_dir.exists()
        archived_files = list(archive_dir.glob("*.json"))
        assert len(archived_files) == 1

        # 归档文件应包含原始 prompt 数据，支持溯源分析
        with open(archived_files[0], "r", encoding="utf-8") as f:
            data = json.load(f)
        assert len(data) == 2
