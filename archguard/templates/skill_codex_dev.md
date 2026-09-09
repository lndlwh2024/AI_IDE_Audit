# IDE_Audit 统一开发守则（A 窗口）

此守则已融合 dual-agent-sync；协同数据统一在 `.ide_audit/`。不要再运行独立旧 Skill。

1. 每次用户需求及补充约束均逐条调用 `record_prompt` 保存原文，禁止改写或合并丢失条件。
2. 使用稳定的小写 IDE 标识和当前窗口会话 ID；首次接入调用 `start_sync_session`，它先建立图谱；已有图谱则基于原图谱刷新。每次再次接入（包括服务重启、恢复旧任务）调用 `enter_sync_session` 立即更新图谱，成功前不得编码。图谱始终由 A 维护，B 不参与写入。任务开始和编辑前调用 `get_sync_updates`，读取全部未读事件及图谱。展示来自其他 IDE 的来源、版本、类型、时间、摘要、影响文件、有效诊断、后续行动；理解后才调用 `acknowledge_sync`，不能跳过中间版本。
3. 未读改动或其他会话的有效编辑意图与本次范围重叠时，先处理冲突，不覆盖他人改动。编辑前调用 `begin_edit` 声明文件范围，成功后才编辑；长时间编辑每 5 分钟调用 `renew_edit`，续期失败立即停止编辑并重新核对冲突；完成记账和图谱维护后调用 `end_edit`。仅修改需求强相关的文件。
4. 使用 `complete_sync_operation` 完成代码、文档、配置、测试、部署、分析和交接事件，同时刷新图谱并生成流水/状态。每个逻辑操作生成稳定 operation_id；失败后以相同编号、原始事件参数和 session_id 重试，禁止换编号重复记账。只有确实不需要图谱交接的独立通知才使用 `record_sync_event`。保留原协议的 12 类事件、完整 context/verification、文件范围与目的；未解决排查使用 diagnostic_record，纠错必须指出 supersedes_version、旧假设和新证据。没有提交时 head_commit 为 null，base_commit 填当前真实 HEAD，不能猜测新 SHA。
5. 结构变化必须声明 graph_impact，统一交接会自动关联实际事件版本；单独维护图谱时使用 `sync_graph` 并关联实际事件版本。原人工维护的模块职责、非 Python 依赖及 API 调用等语义信息不可静默丢弃。确认事件及图谱操作成功后才交接；失败时报告并恢复。
6. 完成开发后只暂存本轮授权的文件，调用 `prepare_audit_commit` 或 `archguard prepare` 固定批次，再自动执行 git commit。也可使用 `archguard commit -m "说明" <本轮路径>`。不提供路径时只提交现有暂存区，不擅自 git add 全部工作区。
7. post-commit 封存客观审计并加入后台队列。提交后调用 `get_audit_status` 查询，出现 dispatch.thread_id 后，使用 Codex 桌面内置 `navigate_to_codex_page` 打开该 B；这是统一插件 A 工作流的必需步骤。可用 `archguard queue-status` 查询同样状态。若工具暂未出现则搜索该内置工具；不可用时报告具体原因和 B 标识，不能谎称已打开。后端使用真实 projectId 校验同项目归属，A 必须核对桌面打开结果。B 尚未出现时保持跟进队列；出现 needs_attention 时展示错误并处理原任务，不重复创建。若 desktop_pending 非空，按顺序处理：dispatch.status 已是 desktop_sending 时先调用 collect_desktop_audit 回收原请求，不得再次领取或发送；尚未领取才调用 claim_desktop_audit；ready 为 true 时将返回 prompt 原文通过桌面内置 send_message_to_thread 发给返回 thread_id，随后使用 wait_threads 等待并调用 collect_desktop_audit 回收真实 B 裁决。ready 为 false 时等待 B 完成上一轮。严禁 A 自行构造裁决，严禁重复领取/发送，严禁为了绕过活动持有者冲突新建 B。同一次 Codex 运行中始终复用当前 B；原 B 被归档或确实不存在才新建 B 并递增编号。跨次运行先尝试恢复/原生派发，只有确认不可恢复才报告并按用户确认的编号策略处理。不要自动删除 B，永久删除必须得到用户明确确认。开发窗口不得代替 B 作最终裁决。必要证据缺失时先修复证据链，禁止编造通过报告。没有用户明确要求不执行 git push。

如果当前任务是 B 审计，以上开发流程不适用：不得记录需求、写协同资产或提交代码，只读取绑定审计任务并裁决答疑。
