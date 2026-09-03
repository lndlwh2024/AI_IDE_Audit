"""architecture_detector 单元测试

验证 9 大维度的规则匹配与信号产出。
使用构造的 DiffResult 对象模拟各类变更场景。
"""

import pytest

from archguard.core.architecture_detector import detect_signals, summarize_signals
from archguard.core.diff_analyzer import DiffResult, FileChange
from archguard.rules.loader import load_default_rules


@pytest.fixture
def default_rules():
    """加载默认规则集供测试用例复用"""
    return load_default_rules()


def _make_diff(files: list[FileChange]) -> DiffResult:
    """辅助函数：构造测试专用的 DiffResult 模拟对象"""
    return DiffResult(
        commit_hash="abc1234567890",
        commit_message="Test commit",
        files=files,
    )


class TestDetectSignals:
    """测试架构变更信号检测的各项业务规则"""

    def test_migration_file_triggers_db_signal(self, default_rules) -> None:
        """新增 migration 文件应触发数据库 Schema 变更信号"""
        diff = _make_diff([
            FileChange(path="app/migrations/0002_add_table.py", change_type="A"),
        ])
        signals = detect_signals(diff, default_rules)
        rule_ids = [s.rule_id for s in signals]
        assert "DB_MIGRATION_FILE" in rule_ids

    def test_route_file_triggers_api_signal(self, default_rules) -> None:
        """修改路由文件应触发 API 变更信号"""
        diff = _make_diff([
            FileChange(path="app/routers/user_router.py", change_type="M"),
        ])
        signals = detect_signals(diff, default_rules)
        rule_ids = [s.rule_id for s in signals]
        assert "API_ROUTE_CHANGE" in rule_ids

    def test_auth_file_triggers_security_signal(self, default_rules) -> None:
        """修改认证相关文件应触发安全边界信号"""
        diff = _make_diff([
            FileChange(path="app/auth/jwt_handler.py", change_type="M"),
        ])
        signals = detect_signals(diff, default_rules)
        rule_ids = [s.rule_id for s in signals]
        assert "SECURITY_AUTH_CHANGE" in rule_ids

    def test_env_file_triggers_config_signal(self, default_rules) -> None:
        """修改 .env 文件应触发配置/环境变更信号"""
        diff = _make_diff([
            FileChange(path=".env.production", change_type="M"),
        ])
        signals = detect_signals(diff, default_rules)
        rule_ids = [s.rule_id for s in signals]
        assert "CONFIG_ENV_CHANGE" in rule_ids

    def test_dockerfile_triggers_config_signal(self, default_rules) -> None:
        """修改 Dockerfile 应触发配置/环境变更信号"""
        diff = _make_diff([
            FileChange(path="Dockerfile", change_type="M"),
        ])
        signals = detect_signals(diff, default_rules)
        rule_ids = [s.rule_id for s in signals]
        assert "CONFIG_ENV_CHANGE" in rule_ids

    def test_schema_file_triggers_contract_signal(self, default_rules) -> None:
        """修改 schemas.py 应触发共享契约变更信号"""
        diff = _make_diff([
            FileChange(path="app/schemas.py", change_type="M"),
        ])
        signals = detect_signals(diff, default_rules)
        rule_ids = [s.rule_id for s in signals]
        assert "SHARED_CONTRACT_CHANGE" in rule_ids

    def test_dir_new_file_triggers_structure_signal(self, default_rules) -> None:
        """新增带目录的文件应触发目录结构变更信号"""
        diff = _make_diff([
            FileChange(path="new_module/core/handler.py", change_type="A"),
        ])
        signals = detect_signals(diff, default_rules)
        rule_ids = [s.rule_id for s in signals]
        assert "DIR_STRUCTURE_NEW_DELETE" in rule_ids

    def test_file_rename_triggers_module_signal(self, default_rules) -> None:
        """文件重命名应触发模块合并/拆分信号"""
        diff = _make_diff([
            FileChange(
                path="app/new_name.py",
                change_type="R",
                rename_from="app/old_name.py",
            ),
        ])
        signals = detect_signals(diff, default_rules)
        rule_ids = [s.rule_id for s in signals]
        assert "MODULE_RENAME_MOVE" in rule_ids

    def test_pure_business_file_no_signal(self, default_rules) -> None:
        """纯业务代码修改应不触发任何架构信号（排除误报）"""
        diff = _make_diff([
            FileChange(path="app/services/user_service.py", change_type="M"),
        ])
        signals = detect_signals(diff, default_rules)
        assert len(signals) == 0

    def test_root_file_add_no_dir_signal(self, default_rules) -> None:
        """根目录下新增文件不应触发目录结构信号（边界测试）"""
        diff = _make_diff([
            FileChange(path="utils.py", change_type="A"),
        ])
        signals = detect_signals(diff, default_rules)
        dir_signals = [s for s in signals if s.rule_id == "DIR_STRUCTURE_NEW_DELETE"]
        assert len(dir_signals) == 0


class TestSummarizeSignals:
    """测试信号汇总统计"""

    def test_summary_counts(self, default_rules) -> None:
        """汇总统计应正确按维度与严重度计数"""
        diff = _make_diff([
            FileChange(path="app/migrations/0001.py", change_type="A"),
            FileChange(path=".env", change_type="M"),
        ])
        signals = detect_signals(diff, default_rules)
        summary = summarize_signals(signals)
        assert summary["total"] >= 2
        assert isinstance(summary["by_severity"], dict)
        assert isinstance(summary["by_dimension"], dict)
