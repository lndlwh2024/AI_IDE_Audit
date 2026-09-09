# 旧项目切换辅助工具（插件之外）

本目录不属于 IDE_Audit 插件包，不进入 wheel，也不被插件安装器或 MCP 调用。它服务于 NEWS 等既有项目的一次性切换；插件功能验收不依赖旧项目业务历史。

已提供的资产转换可保留原始账本、图谱及哈希备份，目标存在资产时拒绝覆盖。需在已安装 IDE_Audit 的 Python 环境中单独运行：

```powershell
python scripts/migrate_ai_sync_to_ide_audit.py --project-root H:/AIcode/Trae/news --dry-run
```

先在 NEWS 的临时副本验证；移除 `--dry-run` 才会转换资产。工具不删除源目录，也不自动修改全局 Skill 安装。不能同时运行新旧两套协同写入流程。

无缝切换的独立验收顺序：

1. 暂停该项目旧工作流，记录旧 Skill 的项目/全局启用引用及配置，并备份；不卸载其他项目仍在使用的全局 Skill。
2. 对副本执行预检、转换与数据校验，验证账本/图谱与当前插件工具兼容。清理或重新获取旧租约，A 使用新的协同会话 ID。
3. 仅停用 NEWS 中确认归属的旧规则引用，安装 IDE_Audit，保留其他开发规则。
4. A 接入后立即刷新图谱、核对未读事件；完成一次受控提交并验证同项目 B、逐文件裁决和追问。
5. 所有检查通过才对原项目执行同样切换；保留旧目录与配置备份，失败时停止写入并恢复旧配置。

完整切换请使用下文 switch_project.py；上面的旧入口仅用于资产转换。真实 NEWS 尚未执行切换，不把副本测试等同于实际业务上线。

## NEWS 格式转换和完整切换入口

使用同目录 `switch_project.py`，需先安装本次 IDE_Audit wheel。默认只有只读预检：

```powershell
python switch_project.py --project-root H:/AIcode/Trae/news
```

加 `--apply` 才停用该项目 `.agents/skills/dual-agent-sync`、`.codex/skills/dual-agent-sync`，转换数据并安装新入口。全局 Skill 和旧 `.ai-sync` 保留。不能在旧写入者仍运行时切换。目标已有新协同资产时拒绝覆盖。

回滚：`python switch_project.py --rollback <返回的 receipt.json 路径>`。校验切换后配置未被他人更改，恢复旧项目 Skill 和配置；新资产移动到回滚记录下保留，不删除。

NEWS 实测：原账本 v0000 起算，转换为 v0001 起算并保留 legacy_version；结构化模块保存为 module_details；结构化符号、额外边类型保留。未知旧事件类型保留 legacy_event_type 并以历史 handoff 承载；只有计数而无明细的 graph_impact 保留原计数并明确标注明细不可用。原始完整资产另有哈希备份。旧未封存事件不绑定首次新提交。

2026-09-09 已在 NEWS 资产副本完成 140 条事件、612 个节点的转换及回滚，源目录哈希不变。同项目原生 B 与活动写入者桥接已经验证，用户接受 B 宿主读写权限。实际 NEWS 切换请先停止旧写入者、执行预检，再显式 --apply；本次交付没有改动真实 NEWS。
