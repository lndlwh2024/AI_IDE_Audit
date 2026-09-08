"""只读事实引擎。输入固定提交及封存证据；不建目录、不归档、不保存结果。"""
from datetime import datetime, timezone
import git
from pydantic import BaseModel, Field
from archguard.core.diff_analyzer import analyze_commit
from archguard.core.architecture_detector import detect_signals, summarize_signals
from archguard.core.graph_analyzer import analyze_graph_changes
from archguard.core.codegraph import graph_at_commit
from archguard.core.ledger_analyzer import verify_ledger_consistency
from archguard.rules.loader import load_default_rules


class AuditResult(BaseModel):
    schema_version: int = 1
    audit_id: str
    timestamp: str
    commit_hash: str
    base_commit: str | None = None
    commit_message: str
    prompts: list[dict] = Field(default_factory=list)
    diff_summary: dict = Field(default_factory=dict)
    changed_files: list[dict] = Field(default_factory=list)
    architecture_signals: list[dict] = Field(default_factory=list)
    signal_summary: dict = Field(default_factory=dict)
    graph_analysis: dict = Field(default_factory=dict)
    ledger_verification: dict = Field(default_factory=dict)
    graph_before: dict = Field(default_factory=dict)
    graph_after: dict = Field(default_factory=dict)
    declared_graph: dict = Field(default_factory=dict)
    declared_graph_before: dict = Field(default_factory=dict)
    ledger_events: list[dict] = Field(default_factory=list)
    analysis_status: str = 'complete'
    diagnostics: list[dict] = Field(default_factory=list)
    input_hash: str = ''


def run_audit(project_root, commit_hash=None, snapshot=None):
    facts = analyze_commit(project_root, commit_hash)
    snapshot = snapshot or {}
    diagnostics = list(snapshot.get('diagnostics', []))
    if not snapshot.get('prompts'):
        diagnostics.append({'component': 'prompts', 'error': '缺少本提交已绑定需求'})
    if not snapshot.get('ledger_events'):
        diagnostics.append({'component': 'ledger', 'error': '缺少本提交的记账申报'})
    repo = git.Repo(project_root)
    before = graph_at_commit(repo, facts.base_commit)
    after = graph_at_commit(repo, facts.commit_hash)
    for graph in (before, after):
        diagnostics.extend(dict(d, component='graph') for d in graph.get('diagnostics', []))
    signals = detect_signals(facts, load_default_rules())
    ledger = verify_ledger_consistency(facts, snapshot.get('ledger_events', []))
    return AuditResult(audit_id=facts.commit_hash, timestamp=datetime.now(timezone.utc).isoformat(),
        commit_hash=facts.commit_hash, base_commit=facts.base_commit, commit_message=facts.commit_message,
        prompts=snapshot.get('prompts', []), ledger_events=snapshot.get('ledger_events', []),
        changed_files=[f.to_dict() for f in facts.files],
        diff_summary={'total_files_changed': facts.total_files_changed, 'total_additions': facts.total_additions,
                      'total_deletions': facts.total_deletions},
        architecture_signals=[s.model_dump(mode='json') for s in signals], signal_summary=summarize_signals(signals),
        graph_before=before, graph_after=after,
        declared_graph=snapshot.get('declared_graph', {}),
        declared_graph_before=snapshot.get('declared_graph_before', {}),
        graph_analysis=analyze_graph_changes(facts, after, before).model_dump(),
        ledger_verification=ledger.model_dump(), diagnostics=diagnostics,
        analysis_status='partial' if diagnostics else 'complete', input_hash=snapshot.get('input_hash', ''))
