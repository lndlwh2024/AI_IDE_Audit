# dual-agent-sync 融合能力对照

核对日期：2026-09-09。原始源由用户提供：`H:\AIcode\Antigravity\skill\dual-agent-sync-skill`，远程为 https://github.com/lndlwh2024/dual-agent-sync 。

源提交为 `45e4463722263584ee7e4eb4b94fcdd299aa9f3f`，存在未提交修改，因此不能仅凭提交号复现当前源内容。已将两份 Skill、MANUAL、PROTOCOL、WORKFLOW、EVENT_SCHEMA 的 SHA256 记录到 [DUAL_SYNC_BASELINE.json](DUAL_SYNC_BASELINE.json)。以这些实际材料作为对照，不用 IDE_Audit 已有模型反推原能力。原仓库及其未提交修改未被修改。

| 原能力 | 当前实现 | 验证与剩余边界 |
|:---|:---|:---|
| 12 类事件及完整上下文 | `sync/schemas.py`；统一 `record_sync_event` | 保留扩展字段；诊断证据接受结构化对象与旧字符串，补齐旧纠错记录可缺省字段 |
| 版本等于账本行号、仅追加 | `sync/ledger.py` | 完整历史校验，OS 锁内分配版本并 fsync；线程和独立进程竞争测试 |
| AUDIT_LOG / PROJECT_STATE | 账本写入后自动派生，可 `rebuild_views` | 包含来源、范围、验证、图谱申报与当前有效诊断，不仅是 summary |
| 稳定 IDE ID 与唯一会话 | `sync/cursor.py` | 小写 IDE；大写前缀、分钟时间戳和 A0001..Z9999；同 IDE 多会话合并 |
| 未读读取、游标检查、全读回退 | `get_sync_updates` / `acknowledge_sync` | 已读末行版本核验；越界/旧格式回退；MCP 不允许确认未交付范围 |
| 编辑意图冲突 | `begin_edit` / `end_edit` | 文件租约、所有者令牌、未读范围冲突；租约过期后旧所有者不能释放新租约 |
| 游标/图谱/账本写互斥 | `storage.transaction` | 持久锁文件 + OS 锁，进程结束自动释放；不以过期时间删除正在使用的互斥锁 |
| 全项目图谱节点和多类型边 | `sync/graph.py`、`update_architecture_graph` | 扫描文件节点，Python AST 导入；人工维护非 Python require/api_call/extends/implements，校验端点 |
| 目的、导出、导入与 API 语义 | 图谱模型扩展字段和人工声明 | 重扫保留人工 purpose、非 Python 边；自动扫描不代表全语言语义解析 |
| 图谱增量及 trigger_version | 图谱日志与可恢复 journal | 先写 journal 再写图谱/日志；MCP 检查关联事件存在。当前仍为全扫描后求差，未完成性能优化 |
| 提交后双尺度裁决 | 统一 A 守则、冻结输入、只读 B 服务 | 新增 V2 能力，不能用旧 Skill 的成功经验替代真实 Codex 验收 |
| 旧目录迁移与备份 | `sync/migration.py` | V1 平铺/V2 分层识别、dry-run、哈希备份、发布回滚；源保留，目标冲突拒绝覆盖 |
| 不再独立运行旧 Skill | 项目统一 A 守则及 MCP 安装入口 | 新入口明确禁用旧工作流；项目外已安装的旧 Skill 尚不自动卸载，应在最终切换验收中核对 |

## 不能宣称 100% 等价的剩余项

1. 原仓库未提交资源需形成可复现归档；真实大型账本、跨 IDE 会话和复杂诊断纠错样本尚未完成完整兼容矩阵。
2. 图谱与账本各自有事务保护，但多个独立 MCP 调用之间尚无跨事件、图谱、游标的统一可恢复工作流事务。A 必须确认各步成功，失败时不能宣布完成交接。
3. 增量扫描性能、长期租约续期、目录级编辑意图及旧 Skill 全局安装位置识别仍需完善。
4. 迁移目前保留原始资产、备份和迁移 manifest；不自动追加一条迁移事件，也不改写历史账本。切换后开发端应记录实际 migration_update 事件。
5. 独立 B 已通过合成项目的真实裁决、桌面任务列表可见、追问、服务端恢复和拒绝编辑验证；自动窗口呈现、长任务和忙碌排队等场景仍需扩展实机验收。

这些是明确保留的开发/验收项，不是 V2.0 需求删减。当前只能标记为融合修复预发布版本。
