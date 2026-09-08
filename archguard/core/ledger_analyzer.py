"""冻结事件范围内的文件与双侧行范围核验，纯只读计算。"""
import re
from pydantic import BaseModel, Field


class LedgerVerificationResult(BaseModel):
    is_consistent: bool
    undeclared_files: list[str] = Field(default_factory=list)
    phantom_files: list[str] = Field(default_factory=list)
    line_deviations: list[dict] = Field(default_factory=list)
    total_diff_files: int = 0
    total_ledger_files: int = 0
    consistency_score: float = 0
    diagnostics: list[dict] = Field(default_factory=list)


def normalize(path):
    from pathlib import PurePosixPath
    path = path.replace('\\', '/')
    if not path or path == '.' or path.startswith('/') or ':' in path or '..' in PurePosixPath(path).parts:
        raise ValueError(f'非法仓库相对路径: {path}')
    return str(PurePosixPath(path))


def extract_diff_files(diff_result):
    return {normalize(f.path) for f in diff_result.files}


def extract_ledger_files(ledger_events):
    files = set()
    for event in ledger_events:
        scope = event.get('scope', {})
        files.update(normalize(fc['file']) for fc in scope.get('files_changed', []))
        files.update(normalize(doc) for doc in scope.get('docs_changed', []))
    return files


def check_line_range_deviation(diff_result, ledger_events):
    declared = {}
    for event in ledger_events:
        for fc in event.get('scope', {}).get('files_changed', []):
            declared.setdefault(normalize(fc['file']), []).extend(fc.get('lines') or [])
    deviations = []
    for file in diff_result.files:
        if file.path not in declared:
            continue
        ranges = {'old': [], 'new': []}
        for item in declared[file.path]:
            match = re.fullmatch(r'(?:(old|new):)?(\d+)(?:-(\d+))?', item)
            if not match:
                deviations.append({'file': file.path, 'error': '非法行范围', 'range': item})
                continue
            side, start, end = match.groups()
            start, end = int(start), int(end or start)
            if start < 1 or end < start:
                deviations.append({'file': file.path, 'error': '非法行范围', 'range': item})
                continue
            # 原协议无侧别的范围同时作用于两侧，保留兼容性。
            for target in ([side] if side else ['old', 'new']):
                ranges[target].append((start, end))
        for side, numbers in [('old', getattr(file, 'deleted_lines', [])), ('new', getattr(file, 'added_lines', []))]:
            missed = [n for n in numbers if not any(a <= n <= b for a, b in ranges[side])]
            if missed:
                deviations.append({'file': file.path, 'side': side, 'undeclared_lines': missed})
    return deviations


def verify_ledger_consistency(diff_result, ledger_events):
    actual, declared = extract_diff_files(diff_result), extract_ledger_files(ledger_events)
    # 重命名允许同时申报旧路径和新路径，不把旧路径误判为虚报。
    rename_sources = {normalize(f.rename_from) for f in diff_result.files if getattr(f, 'rename_from', None)}
    undeclared = sorted(actual - declared)
    phantom = sorted(declared - actual - rename_sources)
    deviations = check_line_range_deviation(diff_result, ledger_events)
    count = len(actual | declared)
    score = 1 - (len(undeclared) + len(phantom) + len({d['file'] for d in deviations})) / count if count else 1
    return LedgerVerificationResult(is_consistent=not (undeclared or phantom or deviations),
        undeclared_files=undeclared, phantom_files=phantom, line_deviations=deviations,
        total_diff_files=len(actual), total_ledger_files=len(declared), consistency_score=max(0, score))
