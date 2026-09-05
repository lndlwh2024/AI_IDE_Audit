from typing import List, Dict, Optional, Literal
from pydantic import BaseModel, Field

class DiagnosticRecord(BaseModel):
    """诊断记录，用于追踪问题排查与解决过程"""
    status: Literal['unresolved', 'corrected']
    symptom: str
    current_best_conclusion: str
    confidence: Literal['low', 'medium', 'high']
    evidence: List[str]
    ruled_out: List[str]
    open_hypotheses: List[str]
    next_actions: List[str]
    do_not_repeat: List[str]
    handoff_prompt: str
    supersedes_version: Optional[str] = None
    invalidated_assumption: Optional[str] = None
    correction_reason: Optional[str] = None

class FileChange(BaseModel):
    """文件修改详情"""
    file: str
    lines: Optional[List[str]] = None
    purpose: Optional[str] = None

class GraphNode(BaseModel):
    """代码图谱节点"""
    module: str
    purpose: str
    exports: Optional[List[str]] = None
    imports: Optional[List[str]] = None
    api_calls: Optional[List[str]] = None

class GraphEdge(BaseModel):
    """代码图谱边，表示依赖或调用关系"""
    # Pydantic v2 中 alias='from' 允许 JSON 序列化使用 "from"，
    # populate_by_name=True 允许 Python 代码中使用 from_= 来构造
    model_config = {"populate_by_name": True}
    from_: str = Field(alias="from")
    to: str
    type: Literal['imports', 'require', 'api_call', 'extends', 'implements']

class GraphMeta(BaseModel):
    """图谱元数据"""
    version: str
    last_updated: str
    updated_by: str
    total_nodes: int
    total_edges: int

class CodeGraph(BaseModel):
    """全局代码图谱"""
    meta: GraphMeta
    modules: List[str]
    nodes: Dict[str, GraphNode]
    edges: List[GraphEdge]

class GraphDiff(BaseModel):
    """图谱差异详情，记录具体的新增/删除节点和边"""
    nodes_added: List[str] = Field(default_factory=list)
    nodes_removed: List[str] = Field(default_factory=list)
    edges_added: List[Dict] = Field(default_factory=list)
    edges_removed: List[Dict] = Field(default_factory=list)

class GraphImpact(BaseModel):
    """事件造成的图谱影响，声明本次变更对架构图谱的具体改动"""
    updated: bool = False
    nodes_added: List[str] = Field(default_factory=list)
    nodes_removed: List[str] = Field(default_factory=list)
    edges_added: List[Dict] = Field(default_factory=list)
    edges_removed: List[Dict] = Field(default_factory=list)

class GraphChangelogEntry(BaseModel):
    """图谱变更日志记录"""
    timestamp: str
    source_ai_ide: str
    action: Literal['init', 'update']
    trigger_version: str
    summary: str
    diff: GraphDiff

class CursorSession(BaseModel):
    """特定会话的读取游标"""
    last_read_version: str
    last_read_line: Optional[int] = None
    last_read_timestamp: Optional[str] = None

class CursorFile(BaseModel):
    """AI IDE 的游标文件结构"""
    ai_ide_id: str
    sessions: Dict[str, CursorSession]

class LockFile(BaseModel):
    """锁文件信息"""
    locked_by: str
    locked_at: str
    scope: Optional[str] = None
    purpose: Optional[str] = None
    expires_at: Optional[str] = None

class GitInfo(BaseModel):
    """Git 状态上下文"""
    branch: Optional[str] = None
    base_commit: Optional[str] = None
    head_commit: Optional[str] = None

class ScopeInfo(BaseModel):
    """变更范围定义"""
    modules: List[str]
    files_changed: List[FileChange]
    docs_changed: List[str]
    files_analyzed: Optional[List[str]] = None

class VerificationInfo(BaseModel):
    """验证结果记录"""
    tests_run: List[str]
    tests_not_run: List[str]
    result: str

class ContextInfo(BaseModel):
    """当前上下文信息汇总"""
    requirement_background: str
    problem_background: str
    solution: str
    current_status: str
    remaining_issues: List[str]
    next_steps: List[str]
    risks: List[str]
    diagnostic_record: Optional[DiagnosticRecord] = None

class LedgerEvent(BaseModel):
    """核心事件模型"""
    version: str
    timestamp: str
    project: str
    source_ai_ide: str
    event_type: Literal[
        'analysis_handoff', 'planning', 'code_update', 'doc_update', 
        'test_update', 'config_update', 'migration_update', 'deployment_update', 
        'bugfix', 'handoff', 'risk_notice', 'conflict_notice'
    ]
    feature_scope: Optional[str] = None
    git: GitInfo
    scope: ScopeInfo
    graph_impact: GraphImpact
    context: ContextInfo
    verification: VerificationInfo
    summary: str
