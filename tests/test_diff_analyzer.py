"""diff_analyzer 单元测试

使用临时 Git 仓库验证：
- 普通 commit 的 diff 解析
- 根提交（首次 commit）的解析
- 文件增删改类型的正确识别
"""

from pathlib import Path

import git
import pytest

from archguard.core.diff_analyzer import analyze_commit


@pytest.fixture
def git_repo(tmp_path: Path) -> git.Repo:
    """创建一个带有初始 commit 的临时 Git 仓库"""
    repo = git.Repo.init(tmp_path)
    # 配置测试用 git 用户信息
    repo.config_writer().set_value("user", "name", "test").release()
    repo.config_writer().set_value("user", "email", "test@test.com").release()
    # 创建初始文件并提交
    readme = tmp_path / "README.md"
    readme.write_text("# Test Project\n")
    repo.index.add(["README.md"])
    repo.index.commit("Initial commit")
    return repo


class TestAnalyzeCommit:
    """测试 commit 分析"""

    def test_root_commit(self, tmp_path: Path) -> None:
        """根提交（首次 commit）应正确解析所有新增文件"""
        repo = git.Repo.init(tmp_path)
        repo.config_writer().set_value("user", "name", "test").release()
        repo.config_writer().set_value("user", "email", "test@test.com").release()
        (tmp_path / "file1.py").write_text("print('hello')\n")
        (tmp_path / "file2.py").write_text("x = 1\n")
        repo.index.add(["file1.py", "file2.py"])
        repo.index.commit("Initial commit")

        result = analyze_commit(tmp_path)
        assert result.total_files_changed == 2
        assert result.commit_message == "Initial commit"
        # 根提交所有文件应为新增类型
        for fc in result.files:
            assert fc.change_type == "A"

    def test_normal_commit_add_file(self, git_repo: git.Repo, tmp_path: Path) -> None:
        """普通 commit 新增文件应识别为 A 类型"""
        new_file = tmp_path / "new_feature.py"
        new_file.write_text("def hello():\n    pass\n")
        git_repo.index.add(["new_feature.py"])
        git_repo.index.commit("Add new feature")

        result = analyze_commit(tmp_path)
        assert result.total_files_changed == 1
        assert result.files[0].change_type == "A"
        assert result.files[0].path == "new_feature.py"

    def test_normal_commit_modify_file(self, git_repo: git.Repo, tmp_path: Path) -> None:
        """普通 commit 修改文件应识别为 M 类型"""
        readme = tmp_path / "README.md"
        readme.write_text("# Test Project\n\nUpdated content\n")
        git_repo.index.add(["README.md"])
        git_repo.index.commit("Update readme")

        result = analyze_commit(tmp_path)
        assert result.total_files_changed == 1
        assert result.files[0].change_type == "M"

    def test_normal_commit_delete_file(self, git_repo: git.Repo, tmp_path: Path) -> None:
        """普通 commit 删除文件应识别为 D 类型"""
        readme = tmp_path / "README.md"
        readme.unlink()
        git_repo.index.remove(["README.md"])
        git_repo.index.commit("Delete readme")

        result = analyze_commit(tmp_path)
        assert result.total_files_changed == 1
        assert result.files[0].change_type == "D"

    def test_commit_hash_recorded(self, git_repo: git.Repo, tmp_path: Path) -> None:
        """结果应记录正确的 commit hash"""
        new_file = tmp_path / "test.py"
        new_file.write_text("x = 1\n")
        git_repo.index.add(["test.py"])
        commit = git_repo.index.commit("Test commit")

        result = analyze_commit(tmp_path)
        assert result.commit_hash == commit.hexsha

    def test_to_dict_serialization(self, git_repo: git.Repo, tmp_path: Path) -> None:
        """结果应可序列化为字典"""
        new_file = tmp_path / "test.py"
        new_file.write_text("x = 1\n")
        git_repo.index.add(["test.py"])
        git_repo.index.commit("Test commit")

        result = analyze_commit(tmp_path)
        d = result.to_dict()
        assert isinstance(d, dict)
        assert "commit_hash" in d
        assert "files" in d
        assert isinstance(d["files"], list)
