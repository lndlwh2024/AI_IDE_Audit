# IDE_Audit 统一开发守则（A 窗口）

此守则已融合 dual-agent-sync；协同数据统一在 `.ide_audit/`。不要再运行独立旧 Skill。

1. 每次用户需求及补充约束均逐条调用 `record_prompt` 保存原文，禁止改写或合并丢失条件。
2. 使用稳定的小写 IDE 标识和当前窗口会话 ID；没有 ID 时调用 `start_sync_session`。任务开始和编辑前调用 `get_sync_updates`，读取全部未读事件及图谱。展示来自其他 IDE 的来源、版本、类型、时间、摘要、影响文件、有效诊断、后续行动；理解后才调用 `acknowledge_sync`，不能跳过中间版本。
3. 未读改动或其他会话的有效编辑意图与本次范围重叠时，先处理冲突，不覆盖他人改动。编辑前调用 `begin_edit` 声明文件范围，成功后才编辑；完成记账和图谱维护后调用 `end_edit`。仅修改需求强相关的文件。
4. 使用标准 `record_sync_event` 记录所有代码、文档、配置、测试、部署、分析和交接。保留原协议的 12 类事件、完整 context/verification、文件范围与目的；未解决排查使用 diagnostic_record，纠错必须指出 supersedes_version、旧假设和新证据。没有提交时 head_commit 为 null，base_commit 填当前真实 HEAD，不能猜测新 SHA。
5. 结构变化必须声明 graph_impact，调用 `sync_graph` 并将 trigger_version 关联实际事件版本。原人工维护的模块职责、非 Python 依赖及 API 调用等语义信息不可静默丢弃。确认事件及图谱操作成功后才交接；失败时报告并恢复。
6. 完成开发后只暂存本轮授权的文件，调用 `prepare_audit_commit` 或 `archguard prepare` 固定批次，再自动执行 git commit。也可使用 `archguard commit -m "说明" <本轮路径>`。不提供路径时只提交现有暂存区，不擅自 git add 全部工作区。
7. post-commit 触发客观审计与独立 B。开发窗口不得代替 B 作最终裁决。必要证据缺失时先修复证据链，禁止编造通过报告。没有用户明确要求不执行 git push。

如果当前任务是 B 审计，以上开发流程不适用：不得记录需求、写协同资产或提交代码，只读取绑定审计任务并裁决答疑。
