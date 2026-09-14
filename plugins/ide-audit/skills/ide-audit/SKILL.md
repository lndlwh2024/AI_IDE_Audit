---
name: ide-audit
description: 在 Codex 桌面项目中启用 IDE_Audit、维护协同图谱和操作记账、在每次提交后启动同项目独立 B 大模型审计，并处理裁决答疑和断线恢复。用于项目接入及已启用项目的开发交接；完整替代独立 dual-agent-sync 的逻辑工作流。
---

# IDE_Audit

首次安装必须先询问当前项目用户授权；仅安装插件不启用。明确同意后才执行接入脚本，并传入 --consent。首次安装：在本 Skill 的插件根目录找到 `scripts/install.py`，使用 Python 3.11+ 执行 `python <绝对脚本路径> --project-root <当前项目绝对路径> --consent`。脚本从随插件发布的 wheel 安装独立项目运行环境和开发 MCP/Hook，保留原配置。依赖从 pip 配置的源安装，使用已有 Codex 登录，不需要新的模型 API Key。安装后重新打开项目任务以加载 MCP；如果工具已经可用，直接接入。不得把插件目录作为用户项目。

旧项目迁移不属于插件，不能自动复制 .ai-sync 或删除旧 Skill。需要切换旧工作流时使用单独交付的外部迁移工具。

仅在 A 执行以下统一开发守则；B 必须遵循独立审计守则，不能调用 A 的维护工具。

# IDE_Audit 统一开发守则（A 窗口）

此守则已融合 dual-agent-sync；协同数据统一在 `.ide_audit/`。不要再运行独立旧 Skill。

## 项目授权与暂停（优先于后续开发步骤）

先查询 get_project_status。未选择时只询问用户是否为当前项目开启完整能力，并说明会使用 Codex 额度；未明确同意不得扫描、记录需求、记账、自动提交或启动 B。明确拒绝后不重复询问。只有明确同意，才运行插件安装脚本 --consent 或 archguard install --consent；授权只属于当前项目。

已暂停时不执行下面的自动步骤。用户在 A/B 任意任务要求暂停，调用 pause_project；保留历史。要求恢复调用 resume_project，仅转为 pending_a。只有 A 可调用 start_sync_session / enter_sync_session 更新图谱和同步检查点，成功后才恢复自动工作。B 不得为恢复全面扫描项目。A 同步失败时保持等待；暂停前需求与准备批次保留归档，不授权新提交。暂停前积压提交不自动重放，确需继续时先核对原 B 再显式 retry-audit。

在发送桌面 B 消息前再次查询项目状态；状态已暂停或修订号与领取时不同，不发送，保留请求供核对。不要把控制指令当开发需求。审计后查询 get_token_usage 并向用户展示本轮及 B 已记录用量；未知/区间统计须明确，不用账户额度代替，不猜数。

1. 每次用户需求及补充约束均逐条调用 `record_prompt` 保存原文，禁止改写或合并丢失条件。
2. 使用稳定的小写 IDE 标识和当前窗口会话 ID；首次接入调用 `start_sync_session`，它先建立图谱；已有图谱则基于原图谱刷新。每次再次接入（包括服务重启、恢复旧任务）调用 `enter_sync_session` 立即更新图谱，成功前不得编码。图谱始终由 A 维护，B 不参与写入。任务开始和编辑前调用 `get_sync_updates`，读取全部未读事件及图谱。展示来自其他 IDE 的来源、版本、类型、时间、摘要、影响文件、有效诊断、后续行动；理解后才调用 `acknowledge_sync`，不能跳过中间版本。
3. 未读改动或其他会话的有效编辑意图与本次范围重叠时，先处理冲突，不覆盖他人改动。编辑前调用 `begin_edit` 声明文件范围，成功后才编辑；长时间编辑每 5 分钟调用 `renew_edit`，续期失败立即停止编辑并重新核对冲突；完成记账和图谱维护后调用 `end_edit`。仅修改需求强相关的文件。
4. 使用 `complete_sync_operation` 完成代码、文档、配置、测试、部署、分析和交接事件，同时刷新图谱并生成流水/状态。每个逻辑操作生成稳定 operation_id；失败后以相同编号、原始事件参数和 session_id 重试，禁止换编号重复记账。只有确实不需要图谱交接的独立通知才使用 `record_sync_event`。保留原协议的 12 类事件、完整 context/verification、文件范围与目的；未解决排查使用 diagnostic_record，纠错必须指出 supersedes_version、旧假设和新证据。没有提交时 head_commit 为 null，base_commit 填当前真实 HEAD，不能猜测新 SHA。
5. 结构变化必须声明 graph_impact，统一交接会自动关联实际事件版本；单独维护图谱时使用 `sync_graph` 并关联实际事件版本。原人工维护的模块职责、非 Python 依赖及 API 调用等语义信息不可静默丢弃。确认事件及图谱操作成功后才交接；失败时报告并恢复。
6. 完成开发后只暂存本轮授权的文件，调用 `prepare_audit_commit` 或 `archguard prepare` 固定批次，再自动执行 git commit。也可使用 `archguard commit -m "说明" <本轮路径>`。不提供路径时只提交现有暂存区，不擅自 git add 全部工作区。
7. post-commit 封存客观审计并加入后台队列。提交后调用 `get_audit_status` 查询，出现 dispatch.thread_id 后，使用 Codex 桌面内置 `navigate_to_codex_page` 打开该 B；这是统一插件 A 工作流的必需步骤。可用 `archguard queue-status` 查询同样状态。若工具暂未出现则搜索该内置工具；不可用时报告具体原因和 B 标识，不能谎称已打开。后端使用真实 projectId 校验同项目归属，A 必须核对桌面打开结果。B 尚未出现时保持跟进队列；出现 needs_attention 时展示错误并处理原任务，不重复创建。若 desktop_pending 非空，按顺序处理：dispatch.status 已是 desktop_sending 时先调用 collect_desktop_audit 回收原请求，不得再次领取或发送；尚未领取才调用 claim_desktop_audit；ready 为 true 时将返回 prompt 原文通过桌面内置 send_message_to_thread 发给返回 thread_id，随后使用 wait_threads 等待并调用 collect_desktop_audit 回收真实 B 裁决。ready 为 false 时等待 B 完成上一轮。严禁 A 自行构造裁决，严禁重复领取/发送，严禁为了绕过活动持有者冲突新建 B。同一次 Codex 运行中始终复用当前 B；原 B 被归档或确实不存在才新建 B 并递增编号。跨次运行先尝试恢复/原生派发，只有确认不可恢复才报告并按用户确认的编号策略处理。不要自动删除 B，永久删除必须得到用户明确确认。开发窗口不得代替 B 作最终裁决。必要证据缺失时先修复证据链，禁止编造通过报告。没有用户明确要求不执行 git push。

如果当前任务是 B 审计，以上开发流程不适用：不得记录需求、写协同资产或提交代码，只读取绑定审计任务并裁决答疑。

用户明确拒绝首次开启时，用 `archguard --project-root <当前项目> decline --confirmed` 保存选择，后续不重复询问。该命令必须在用户明确拒绝后执行。

尚未安装项目运行环境时，明确拒绝可用插件内 `python <插件目录>/scripts/session_start.py --decline --confirmed --project-root <当前项目>` 留存选择，不需要下载依赖。


## 用量与增量交接（0.4.1，优先执行）

A 在首次同步、修改前核对账本、commit 后更新图谱/账本这三个阶段，先用当前真实 Codex 任务 ID 调用 begin_token_phase，phase 分别为 initial_sync / before_edit / after_commit。阶段完成或失败后立即 finish_token_phase，并原样打印 display（本次及本窗口累计 token）；不要等整轮开发结束才汇报。结果是宿主已观测区间，最终回复尚未结算时如实说明，不用额度百分比换算 token。不应重复输出完整用量日志。

get_sync_updates 默认分页；阅读并确认当前页后才继续下一页。无新事件时不要读取全账本或全图。enter_sync_session、sync_graph、prepare_audit_commit 返回摘要，完整数据已保存本地，不要为了拿到完整 JSON 再用 shell 打印它们。只在本次任务确实缺证时按文件取局部图谱；不要反复重做迁移资产核对。新任务创建新协同游标可能需读取历史；恢复原任务必须复用已有 session_id，不要每次 start 新会话。

B 完成后立即 get_token_usage 并展示本轮和 B 窗口累计。B 名称为 🔔<项目名>项目审计窗口-<序号>，归档或确实删除后新建才递增，新 B 不回放旧聊天。证据包超过预算时停止并报告，不绕过限制把整个文件包直接塞进对话。保留同一 B 会话也会携带历史上下文，不能承诺其输入开销永远恒定。

提交前通过 complete_sync_operation 维护图谱/账本也需独立计量，phase=prepare_commit，完成后立即打印。用量不可用不阻断已授权同步。若手工命令环境返回空 Codex 项目列表，优先使用宿主 MCP；需要本地执行权限时走宿主审批，不移除项目校验、不反复扫描。

若单条事件超过分页预算，用 get_sync_event_chunk 从 offset=0 顺序读取 next_offset，complete=true 后才 acknowledge_sync，不能跳段或整条打印绕过预算。

为减少长上下文的重复模型调用，宿主支持工具编排时，将 begin_token_phase 与该阶段第一个业务调用放在同一次编排中顺序执行，将最后一个业务调用与 finish_token_phase 放在同一次编排中顺序执行；涉及阅读理解或用户授权的步骤不能盲目批量确认。累计数为宿主当前计数，计数器重置前的历史不宣称完整覆盖。

## 0.4.2 小改动执行约束（覆盖旧步骤中的重复操作）

get_project_status 的 ready_sync_sessions 已含本会话且状态 enabled 时，不再 enter_sync_session/start_sync_session，不重复首次同步计量。新服务首次接入或恢复待同步时仍必须由 A 更新。

普通说明文档的新增不自动成为架构节点；未改变语义图谱时不递增图谱版本、不重写图谱摘要。仍记录文档事件及真实行范围，原有人工架构节点保留。complete_sync_operation 工具已公开事件字段结构，按实际 schema 填写，不能猜字段名；不用反复读取插件源码确认格式。

尽量减少模型往返：将授权状态、必要同步、需求记录、增量核对合并为一组；阅读并处理确有的未读冲突后，完成编辑；将已获授权的记账、单文件暂存、准备、提交和状态查询按依赖顺序在同一次工具编排完成。不得跳过阅读理解、租约、独立 B 或用户审批以减少轮次。不要仅为查询阶段用量增加一次模型调用。

计数没有新增观测时显示“待结算/未知”，不是本次零消耗；本窗口累计包含开发与上下文输入。出现明确工具错误后按返回原因处理；未知错误停止该测试并交接插件开发任务，不在业务 A 中反复扫描插件源码、重跑整个提交流程或重复 commit。

Hook 的 audit --notify 先入队后输出短摘要；无需在 A 中打印完整本地报告。若需恢复已提交的失败任务，先查原提交状态，确认未派发才重试同一提交，不补造或改写已封存的需求和账本。


## 0.4.3 分环节日志与无改动规则（优先执行）

没有代码或受管理文档变化时，不新增修改账本事件。已有改动尚未 commit 时，在完成一项有意义的修改或交接前记一次增量；不得每改一行记账。图谱语义未变则不更新版本。读取、锁及用量日志是运行元数据，不是修改账本。

MCP 自动为检查、增量阅读、加锁/续锁/解锁、记账、图谱维护、提交准备和派发工具记录耗时、请求/响应字符及字节数、成功/失败与阶段标识，位于 .ide_audit/operation-usage/。提交入队和 B 完成也自动留记录。日志不保存源码或提示词正文，不调用模型。直接使用 Python/CLI 绕过 MCP 的维护步骤不具有逐工具日志，因此验证这些环节时使用 MCP。

A 可使用 initial_sync、before_edit、align_updates、edit_lock、record_changes、graph_update、edit_unlock、prepare_commit、after_commit、dispatch 阶段；B 使用 audit。按有意义的模型交互区间 begin_token_phase / finish_token_phase，立即展示 display。不要为本地锁和每个工具单独增加模型往返；同组工具用一对阶段快照，工具明细自动记录。阶段不要嵌套或并行；measurement_id 仅关联当前 MCP 服务顺序调用，不能视为精准独占 token 归因。没有新宿主观测必须显示未知/待结算。

get_operation_usage_log 分页取摘要（最多 20 条），不要把完整日志放入模型上下文。实际用量记录含输入、缓存输入、输出和累计；缓存输入属于输入的一部分，不能再次相加。B 日志按 thread_id + turn_id 去重；不同或重叠阶段不能相加作为费用。响应字符只是新增数据规模，不是模型总输入；长 A 上下文仍可能使每次调用昂贵。

继续已提交但送审失败的任务，含义是对原 audit_id 查询状态、核对未派发后 retry-audit；不撤销、不新增、不修改原 commit，不改写封存账本。单次明确错误按原因处理，不在业务 A 中反复调试插件。


## 0.4.4 完整报告与用量绑定

A 记录各阶段 measurement_id，prepare_audit_commit(measurement_ids=[本轮各阶段ID]) 时一起封存，提交后 begin_token_phase 传目标 audit_id。否则报告无法准确归属该阶段，应显示未绑定，不能拿其他开发计数补填。同阶段多区间分行展示，不强行相加。零字节新文件必须记文件事件；有新增内容必须申报实际行范围。无修改不得制造事件。

派发前可 estimate_audit_usage 获取证据载荷预测；这是字符启发式，不是包括旧上下文的总消耗。B 已完成时必须 get_final_audit_report 并完整展示 markdown，包含审计一、审计二、最终结论和 token 表；不要只打印 JSON 或一句“合理/不合理”。已完成的历史裁决只需重新排版，不再发送给 B 重审。缺失历史用量标记未知，不补造。


## 0.4.5 展示归属与自动计量（覆盖 A 展示完整报告的旧规则）

完整审计报告属于 B。A 仅显示自己的阶段用量、派发状态、B 名称/入口，禁止在 A 重印四段完整报告。B 按四段格式完成最终回复，回收后的已结算报告由插件写入 .ide_audit/reports/<SHA>.md。A 回收后用 Codex 内置 open_in_codex，target 为该报告绝对路径的 file，threadId 明确指定已核对同项目的 B，让文件出现在 B 面板；然后打开 B。这只展示本地文件，不再向 B 发送一次“重印报告”的模型请求。宿主无法打开文件时提供报告路径和 B 入口，明确交付阻塞，不改在 A 打印全文。

A 第一段 begin_token_phase 必须传当前真实任务 ID；后续同一 MCP 服务的 prepare_audit_commit 会自动收集该 A、同开发基线的阶段 ID，返回 usage_measurement_count；不再依赖手工传 ID 清单。服务重启后先用当前真实任务 ID 开始必要的新阶段，已有同基线记录仍会收集。显式 measurement_ids 兼容保留。提交后阶段必须传 audit_id。未获得有效用量时报告原因，不虚报为零。

窗口累计独立保存最近宿主观测，与某一阶段有没有记录无关。B 排版时刷新已绑定 A 的窗口累计，列明任务及观测时间。阶段区分“无阶段记录”“阶段尚未结束”“待结算”“计数缺失/重置”；共享区间标出父阶段，不重复相加。未执行的步骤不需要为了凑表做假动作。不要把无记录自动解释为未执行。


## 0.4.6 运行版本验收（必须在编辑/记账之前）

get_project_status 返回 runtime.running_version、installed_version、restart_required 和 capabilities。先核对这份正在运行的 MCP 自报结果；磁盘 pip 版本不能替代运行版本。缺少 runtime、缺少 automatic_phase_binding/prepared_usage_count 或 restart_required=true 时，停止业务操作并刷新宿主 MCP；不能先编辑再到提交准备发现旧协议。旧服务可继续查询状态或暂停，但不能继续记账、准备和派发。0.4.5 及更早服务本身没有此保护，首次升级必须刷新连接。

测试已编辑并记账但尚未提交时，恢复应复用当前暂存文件和既有事件。不能重新按“文件必须不存在”流程创建文件，不能重复记录同一修改。新运行服务创建恢复阶段并验证用量，准备批次重新生成；历史没有开发基线的阶段记录不得伪装成新绑定记录。


## 0.4.7 传输关闭时的独立 CLI 恢复

不要终止宿主或 MCP 子进程来尝试恢复，也不要把独立 app-server 的 reload 成功视为桌面现有连接更新。Transport closed 表示当前连接不可用；重复调用同一工具不能修复连接。

当前已授权 A 可用项目 .ide_audit/runtime/Scripts/python.exe，以 -I -X utf8 -m archguard.cli.main --project-root <绝对项目目录> 执行独立 CLI：runtime-status、phase-begin --thread-id <真实A> --phase prepare_commit、phase-finish <ID>、prepare --usage-thread-id <真实A>、queue-status、desktop-claim <SHA>、desktop-collect <SHA>。每次启动当前安装版本，不依赖桌面坏连接。该入口不绕过项目授权、任务身份、固定证据或防重复派发。

恢复已记账未提交的工作时复用原暂存文件与事件，先开始新恢复阶段再 prepare，核对短摘要中的 usage_measurement_count。prepare 不再打印全图谱。实际 Git 提交仍只在用户授权后执行，post-commit Hook 负责入队。桌面桥接 claim/collect 沿用原请求状态和原 B；ready=true 才通过宿主原生 send_message_to_thread 发送返回 prompt，不自行编造裁决；已领取时仅 collect，不重复发送。collect 只返回报告路径，完整报告在 B 展示。

runtime-status 只证明当前 CLI 进程版本，不能宣称原 MCP 已恢复。本地操作明细不经 MCP 时无逐工具日志，阶段与入队/B 用量仍保留，须如实注明恢复入口。若需恢复桌面 MCP，可由用户完全退出后台后重启或在同项目新建任务验证，不再自动杀进程。


## 0.4.8 载荷与报告交付契约（替代旧版仅检查裁决完成）

B 守则已整合为单份短文，不再在 B 追加开发/升级历史。事实包保留需求原文、提交 diff、相关图谱及账本；全局孤立节点与环只发送数量和涉及本次文件的条目。完整 B 消息上限 24000 字符，超限停止而不是截断证据。状态查询不再重复返回派发 prompt。

裁决回收成功仅代表 audit_status=completed。检查 delivery.report_delivery_status / collect 返回的 report_delivery_status，requires_b_panel 表示还必须用 open_in_codex 把 report_path 打开到 thread_id 指定的 B 面板。不得只贴机器 JSON 或称整套完成。旧 B 可能保留早期高优先级“仅 JSON”指令，普通新派发消息不能可靠覆盖；此时保留原 B，不重复审计，以其真实裁决生成完整四段文件作为可读交付。不得伪称旧 B 聊天指令已更新。

已完成历史审计可用独立 CLI report-delivery --audit-id <SHA> 本地生成完整报告并获取 B 面板交付信息，不再调用模型审计。B 的本轮 token 必须按当前 audit_id 匹配，尚未回收时不能用上一轮计数代替。


0.4.9 输入协议：audit_one 包含唯一实际 diff 和插件物理核验；information 包含本轮需求、原始账本、变化图谱及上游。图谱前后节点值按 node_values 标识引用。get_audit_input_manifest 和最终报告提供分类 token 粗估及占比，不是宿主字段实测。不要重复读取整份事实包或为排版重发审计。


## 0.4.10 接管与局部图谱维护（覆盖旧全量接管规则）
新 A 或身份/已读位置未知时，只读取最近 2 条账本；确认这两条后即完成接管，后续只读新增，不补读早期历史。原 A 重连时 start_sync_session/enter_sync_session 传当前真实 Codex 任务 ID（thread_id），插件恢复该任务已读位置；不能拿插件连接编号当任务 ID。身份无法取得时按最近两条兜底。enter_sync_session 返回 session_id，后续使用返回值，不坚持使用失效编号。新 A 阅读当前图谱摘要和必要节点、当前有效问题，不加载整份历史流水。
先用 get_working_graph 指定相关文件，取得当前工作态节点和版本；不要把上一提交审计快照当成当前图谱。图谱职责/业务关系更新优先使用 patch_architecture_graph：只传 nodes_upsert（局部字段）、nodes_remove、edges_add、edges_remove、expected_version 与真实账本 trigger_version。删除节点时插件清理关联边；版本冲突只重读相关节点后调整，不重新提交整个项目图谱。旧完整图谱接口仅兼容保留。
开发中插件维护需求、锁、账本和图谱，commit 前封存申报；只有 commit 成功后执行审计一及 B 审计二。无实际修改不制造修改事件；修改但未提交仍记账。程序全量读取本地账本不等于发送全文给模型。
