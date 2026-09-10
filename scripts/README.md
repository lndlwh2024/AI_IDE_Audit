# NEWS 快速切换（插件之外，0.4.0）

此工具与 NEWS 历史需求有关，不进入 IDE_Audit wheel、插件 ZIP 或 MCP。保留全部 `.ai-sync` 原始资产，转换账本与图谱的必要格式；无迁移回滚、新旧双写流程。历史 migrate 入口仅在 Git 历史/源码中留存，不随本次工具包提供使用入口。

当前真实 NEWS 只读预检通过：140 条事件、612 个节点、11 个资产文件。尚未改动真实 NEWS。该项目有未提交修改，不能用迁移操作提交或覆盖这些业务改动。

## 实际操作顺序

1. 在 NEWS 的 A“排查多模式附件与判定问题”停止旧 Skill 写入。保留当前未提交业务文件，不为迁移强行提交。先使用本次发布 wheel 的独立 Python 环境运行下面的预检；不要先安装新项目入口写入空图谱。
2. 明确授权 NEWS 后执行 `--apply --consent`。脚本核验真实 Codex 项目、转换并核对旧资产哈希，安装新守则/MCP/Hook；把该项目旧 Skill 移到 `.ide_audit/legacy-assets/disabled-skills` 保留，停止重复写入。原 `.ai-sync` 的账本、游标、变更日志和其他资产原样保留，不导入旧租约。
3. 重新进入 NEWS 的 A，加载新 MCP；调用 start_sync_session 建立新会话。由 A 将保留的图谱更新到当前 HEAD/工作区，核对同步信息。失败保留 pending_a，修复新插件或转换结果；B 不大范围扫描。
4. NEWS 的 A 在下一次用户授权的实际开发提交中封存需求和申报，验证同项目原生 B 的逐文件裁决与用量。不要提交现有全部脏文件，也不要虚构一次业务变更来宣布成功。
5. 执行 `--finalize` 核验 A 接入、旧资产不再变化、真实 B 裁决已落盘；此时才记为迁移完成。旧 Skill 文件只作归档，不重新启用。使用“暂停当前项目 IDE_Audit”可以暂停新插件，资产不删。

在安装本次 wheel 的 Python 环境运行（发布的 project-switch ZIP 解压后，保持两个脚本在同一目录）：

```powershell
python -m pip install <发布目录>/ide_audit-0.4.0-py3-none-any.whl
python <外部工具目录>/switch_project.py --project-root H:/AIcode/Trae/news
python <外部工具目录>/switch_project.py --project-root H:/AIcode/Trae/news --apply --consent
# NEWS 的 A 完成接入和实际提交审计之后：
python <外部工具目录>/switch_project.py --project-root H:/AIcode/Trae/news --finalize
```

安装 MCP 会绑定执行此脚本的 Python，因此运行环境需长期保留；不要使用即将删除的临时目录。切换记录位于 `.ide_audit/cutover/fast-switch.json`，转换后为 awaiting_a_validation，验证后为 completed。重复运行不会覆盖已经由 A 更新的新资产。全局 Skill 不自动卸载，以免影响其他项目；NEWS 的新守则明确禁止再运行旧 Skill。

旧版本转换为 v0001 起算并保留 legacy_version；结构化模块保存为 module_details，符号及额外依赖保留。未知旧事件保留原类型并作为历史 handoff；缺失图谱明细明确标注，不编造。旧未封存事件不授权首次新提交。
