"""Git Diff 物理事实解析器

通过 GitPython 提取 HEAD~1..HEAD 的变更事实。
严格限定审计范围为最后一次 commit，不翻旧账也不漏新账。

特殊处理：
    - 首次 commit（根提交/Initial Commit）：无 HEAD~1，使用 diff-tree --root
    - 空仓库或无 commit 时：返回空结果
"""

import logging
from dataclasses import dataclass, field
from pathlib import Path

import git

logger = logging.getLogger(__name__)


@dataclass
class FileChange:
    """单个文件的变更信息"""
    path: str                    # 文件路径
    change_type: str             # 变更类型：A(新增) M(修改) D(删除) R(重命名)
    additions: int = 0           # 新增行数
    deletions: int = 0           # 删除行数
    rename_from: str | None = None  # 重命名时的原路径

    def to_dict(self) -> dict:
        """转为可序列化的字典"""
        result = {
            "path": self.path,
            "change_type": self.change_type,
            "additions": self.additions,
            "deletions": self.deletions,
        }
        if self.rename_from:
            result["rename_from"] = self.rename_from
        return result


@dataclass
class DiffResult:
    """一次 commit 的完整 diff 分析结果

    包含该 commit 的所有变更文件信息及统计摘要。
    这是纯粹的物理事实数据，不含任何主观判断。
    """
    commit_hash: str = ""
    commit_message: str = ""
    files: list[FileChange] = field(default_factory=list)

    @property
    def total_files_changed(self) -> int:
        return len(self.files)

    @property
    def total_additions(self) -> int:
        return sum(f.additions for f in self.files)

    @property
    def total_deletions(self) -> int:
        return sum(f.deletions for f in self.files)

    def to_dict(self) -> dict:
        """转为可序列化的字典"""
        return {
            "commit_hash": self.commit_hash,
            "commit_message": self.commit_message,
            "total_files_changed": self.total_files_changed,
            "total_additions": self.total_additions,
            "total_deletions": self.total_deletions,
            "files": [f.to_dict() for f in self.files],
        }


def analyze_commit(repo_path: str | Path) -> DiffResult:
    """分析最后一次 commit 的变更

    严格限定范围为 HEAD~1..HEAD（最后一次 commit），
    对首次 commit（根提交）做特殊兼容处理。

    Args:
        repo_path: Git 仓库根目录路径

    Returns:
        DiffResult 对象，包含完整的变更事实

    Raises:
        git.InvalidGitRepositoryError: 非有效 Git 仓库
        ValueError: 仓库无任何 commit
    """
    repo = git.Repo(str(repo_path))

    # 确保仓库至少有一次 commit
    try:
        head_commit = repo.head.commit
    except ValueError as e:
        raise ValueError(f"仓库尚无任何 commit: {e}") from e

    result = DiffResult(
        commit_hash=head_commit.hexsha,
        commit_message=head_commit.message.strip(),
    )

    # 判断是否为根提交（首次 commit，无父节点）
    if not head_commit.parents:
        # 根提交：与空树对比，所有文件都是新增
        logger.info("检测到根提交（首次 commit），使用空树对比")
        result.files = _diff_root_commit(head_commit)
    else:
        # 普通提交：对比 HEAD~1..HEAD
        parent = head_commit.parents[0]
        logger.info("对比 %s..%s", parent.hexsha[:7], head_commit.hexsha[:7])
        result.files = _diff_two_commits(parent, head_commit)

    logger.info(
        "Diff 分析完成: %d 个文件变更, +%d -%d",
        result.total_files_changed,
        result.total_additions,
        result.total_deletions,
    )
    return result


def _diff_root_commit(commit: git.Commit) -> list[FileChange]:
    """处理根提交：直接遍历树中所有文件

    根提交（首次 commit）没有父提交。树中的所有具体文件（blob）均为新增。
    直接遍历 commit.tree 避免了对本地 Git 空树对象的依赖，更健壮可靠。
    """
    changes: list[FileChange] = []
    for item in commit.tree.traverse():
        if item.type == "blob":
            additions = 0
            try:
                data = item.data_stream.read()
                additions = len(data.splitlines())
            except Exception:
                pass
            changes.append(
                FileChange(
                    path=item.path,
                    change_type="A",
                    additions=additions,
                    deletions=0,
                )
            )
    return changes


def _diff_two_commits(
    parent: git.Commit, current: git.Commit
) -> list[FileChange]:
    """对比两个 commit 之间的差异"""
    diffs = parent.diff(current)
    return _parse_diffs(diffs)


def _parse_diffs(
    diffs: git.DiffIndex, is_root: bool = False
) -> list[FileChange]:
    """将 GitPython 的 DiffIndex 解析为 FileChange 列表

    GitPython 的 diff 对象中 change_type 字段说明：
    - A: 文件新增
    - D: 文件删除
    - M: 文件修改
    - R: 文件重命名/移动
    """
    changes = []
    for diff in diffs:
        change_type = diff.change_type or ("A" if is_root else "M")

        # 确定文件路径：优先使用 b_path（目标端），删除时用 a_path（源端）
        if change_type == "D":
            file_path = diff.a_path
        else:
            file_path = diff.b_path or diff.a_path

        fc = FileChange(
            path=file_path,
            change_type=change_type,
        )

        # 重命名时记录原路径
        if change_type in ("R", "R100") or (diff.renamed_file):
            fc.change_type = "R"
            fc.rename_from = diff.a_path

        # 统计增删行数（需要 diff 的具体内容）
        try:
            diff_text = diff.diff
            if diff_text:
                if isinstance(diff_text, bytes):
                    diff_text = diff_text.decode("utf-8", errors="replace")
                for line in diff_text.splitlines():
                    if line.startswith("+") and not line.startswith("+++"):
                        fc.additions += 1
                    elif line.startswith("-") and not line.startswith("---"):
                        fc.deletions += 1
        except (UnicodeDecodeError, AttributeError):
            # 二进制文件或编码异常时跳过行数统计
            logger.debug("跳过行数统计（可能为二进制文件）: %s", file_path)

        changes.append(fc)

    return changes
