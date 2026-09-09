# dual-agent-sync 融合能力对照

产品继承逻辑能力，旧项目业务数据转换独立于插件。当前版本 0.3.0。

核对日期：2026-09-09。原始源由用户提供：`H:\AIcode\Antigravity\skill\dual-agent-sync-skill`，远程为 https://github.com/lndlwh2024/dual-agent-sync 。

源提交为 `45e4463722263584ee7e4eb4b94fcdd299aa9f3f`，存在未提交修改，因此不能仅凭提交号复现当前源内容。已将两份 Skill、MANUAL、PROTOCOL、WORKFLOW、EVENT_SCHEMA 的 SHA256 记录到 [DUAL_SYNC_BASELINE.json](DUAL_SYNC_BASELINE.json)。以这些实际材料作为对照，不用 IDE_Audit 已有模型反推原能力。原仓库及其未提交修改未被修改。

| 原能力 | 当前实现 | 验证与剩余边界 |
|:---|:---|:---|
| 12 类事件及完整上下文 | `sync/schemas.py`；统一 `record_sync_event` | 保留扩展字段；诊断证据接受结构化对象与旧字符串，补齐旧纠错记录可缺省字段 |
| 版本等于账本行号、仅追加 | `sync/ledger.py` | 完整历史校验，OS 锁内分配版本并 fsync；线程和独立进程竞争测试 |
| AUDIT_LOG / PROJECT_STATE | 账本写入后自动派生，可 `rebuild_views` | 包含来源、范围、验证、图谱申报与当前有效诊断，不仅是 summary |
| 稳定 IDE ID 与唯一会话 | `sync/cursor.py` | 小写 IDE；大写前缀、分钟时间戳和 A0001..Z9999；同 IDE 多会话合并 |
| 未读读取、游标检查、全读回退 | `get_sync_updates` / `acknowledge_sync` | 已读末行版本核验；越界/旧格式回退；MCP 不允许确认未交付范围 |
| 编辑意图冲突 | `begin_edit` / `end_edit` | 文件及目录范围租约、显式续期、所有者令牌、未读范围冲突；租约过期后旧所有者不能释放新租约 |
| 游标/图谱/账本写互斥 | `storage.transaction` | 持久锁文件 + OS 锁，进程结束自动释放；不以过期时间删除正在使用的互斥锁 |
| 全项目图谱节点和多类型边 | `sync/graph.py`、`update_architecture_graph` | 扫描文件节点，Python AST 导入；人工维护非 Python require/api_call/extends/implements，校验端点 |
| 目的、导出、导入与 API 语义 | 图谱模型扩展字段和人工声明 | 重扫保留人工 purpose、Python 手工边、非 Python 边；自动扫描不代表全语言语义解析 |
| 图谱增量及 trigger_version | 图谱日志与可恢复 journal | 先写 journal 再写图谱/日志；MCP 检查关联事件存在。新增文件/stat 与 AST 缓存，未变 Python 零读取/解析；每轮重关联依赖以处理新增模块 |
| 提交后双尺度裁决 | 统一 A 守则、冻结输入、原生 B 模型及只读事实服务 | 新增 V2 能力，不能用旧 Skill 的成功经验替代真实 Codex 验收 |
| 旧目录迁移与备份 | 插件外 `scripts/legacy_sync_assets.py` | V1 平铺/V2 分层识别、dry-run、哈希备份、发布回滚；源保留，目标冲突拒绝覆盖 |
| 不再独立运行旧 Skill | 项目统一 A 守则及 MCP 安装入口 | 新入口明确禁用旧工作流；外部 switch_project 停用当前项目旧 Skill；不删除其他项目使用的全局 Skill |


## 补齐的工作流及验证范围

`complete_sync_operation` 以稳定操作编号连接事件追加、图谱/日志发布、视图重建和安全游标推进；journal 在中断后恢复原候选图，不重复记账，不跳过其他未读事件。目录冲突、租约续期、增量等价及半条追加恢复均有测试。完整回归 103 项通过，真实原生 B 多轮及归档替代见 HOST_COMPATIBILITY。

NEWS 外部工具 switch_project.py 默认只读预检，显式 apply 才转换并切换项目入口，支持 receipt 回滚。140 事件/612 节点的真实资产副本已通过转换和回滚；实际 NEWS 未切换。转换标明旧字段与缺失信息，不将旧事件冒充新提交申报。

“完整逻辑替代”不表示自动解析所有语言语义：原工作流中的人工职责、非 Python 依赖/API 等信息仍由 A 维护；自动物理扫描目前解析 Python 导入，并列出其他文件节点。原仓库未提交内容的哈希已留档，不复制旧业务资源进插件。跨系统领取/发送中断需要核对原 B，整桌面强退重启和其他宿主版本尚未实测。
