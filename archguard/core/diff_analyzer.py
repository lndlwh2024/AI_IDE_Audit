"""只读提取固定提交相对第一父提交的文件状态、patch 和双侧行号。"""
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
import git


@dataclass
class FileChange:
    path: str
    change_type: str
    additions: int = 0
    deletions: int = 0
    rename_from: str | None = None
    diff_content: str = ''
    added_lines: list[int] = field(default_factory=list)
    deleted_lines: list[int] = field(default_factory=list)
    binary: bool = False
    old_mode: int | None = None
    new_mode: int | None = None

    def to_dict(self):
        return asdict(self)


@dataclass
class DiffResult:
    commit_hash: str = ''
    commit_message: str = ''
    files: list[FileChange] = field(default_factory=list)
    base_commit: str | None = None

    @property
    def total_files_changed(self):
        return len(self.files)

    @property
    def total_additions(self):
        return sum(f.additions for f in self.files)

    @property
    def total_deletions(self):
        return sum(f.deletions for f in self.files)

    def to_dict(self):
        return dict(commit_hash=self.commit_hash, base_commit=self.base_commit,
                    commit_message=self.commit_message, files=[f.to_dict() for f in self.files],
                    total_files_changed=self.total_files_changed,
                    total_additions=self.total_additions, total_deletions=self.total_deletions)


def parse_patch(change):
    old_line = new_line = 0
    in_hunk = False
    for line in change.diff_content.splitlines():
        match = re.match(r'^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@', line)
        if match:
            old_line, new_line = map(int, match.groups())
            in_hunk = True
        elif in_hunk and line.startswith('+'):
            change.added_lines.append(new_line)
            new_line += 1
        elif in_hunk and line.startswith('-'):
            change.deleted_lines.append(old_line)
            old_line += 1
        elif in_hunk and line.startswith(' '):
            old_line += 1
            new_line += 1
    change.additions = len(change.added_lines)
    change.deletions = len(change.deleted_lines)


def analyze_commit(repo_path: str | Path, commit_hash: str | None = None) -> DiffResult:
    repo = git.Repo(str(repo_path))
    try:
        head = repo.commit(commit_hash) if commit_hash else repo.head.commit
    except (ValueError, git.BadName) as exc:
        raise ValueError('仓库没有有效的目标提交') from exc
    parent = head.parents[0] if head.parents else None
    result = DiffResult(head.hexsha, head.message.strip(), base_commit=parent.hexsha if parent else None)
    # 文件状态和 patch 分开获取；不依赖 create_patch 模式下为空的 change_type。
    diffs = parent.diff(head, M=True) if parent else head.diff(git.NULL_TREE)
    for diff in diffs:
        kind = diff.change_type or 'M'
        path = diff.a_path if kind == 'D' else diff.b_path or diff.a_path
        change = FileChange(path=path, change_type=kind,
                            rename_from=diff.a_path if kind == 'R' else None,
                            old_mode=diff.a_mode, new_mode=diff.b_mode)
        paths = list(dict.fromkeys(p for p in (diff.a_path, diff.b_path) if p))
        if parent:
            patch = repo.git.diff('--no-ext-diff', '--no-textconv', '--no-color', '--unified=3',
                                  '--find-renames', parent.hexsha, head.hexsha, '--', *paths)
        else:
            patch = repo.git.show('--format=', '--root', '--no-ext-diff', '--no-textconv',
                                  '--no-color', '--unified=3', head.hexsha, '--', *paths)
        change.diff_content = patch
        change.binary = 'Binary files ' in patch or 'GIT binary patch' in patch
        parse_patch(change)
        result.files.append(change)
    return result
