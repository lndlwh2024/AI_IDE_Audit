# IDE_Audit

融合协同记账、架构图谱与原生 Codex 独立审计的插件，版本 **0.3.0**。

A 每次接入先建立或刷新图谱，开发后封存原始需求和提交证据。B 位于同一 Codex 项目，使用现有账户的大模型判断架构授权及每个改动文件的需求相关性；夹带无关文件即判不合理。

## 安装

从本仓库 GitHub Releases 下载 `ide-audit-0.3.0-plugin.zip` 并解压。包内含统一 Skill、项目安装脚本及 wheel；Python 3.11+、Git、已登录 Codex 桌面和 CLI 为前提，首次安装依赖需要网络。

```powershell
python <解压目录>/ide-audit/scripts/install.py --project-root <项目绝对路径>
```

安装器创建项目隔离环境，保留已有配置，安装统一 A 守则、MCP 和 post-commit Hook。重新打开该项目任务加载 MCP，A 立即接入建图或刷新；不要把插件目录当业务项目。若已在 Codex 安装统一插件，也可直接调用 ide-audit Skill 完成此步骤。

开发者可 `python -m pip install .` 后运行 `archguard --project-root <路径> install`。本项目通过 GitHub 交付，不宣称已经发布 PyPI。旧项目切换工具为单独的 `ide-audit-0.3.0-project-switch.zip`，不进入插件或 wheel。

## 工作流程

1. A 逐条保存需求，读取并确认协同更新，检查编辑冲突和租约。
2. 开发完成后以稳定操作编号完成事件、图谱及交接；只暂存授权文件，prepare 后 commit。
3. Hook 封存固定提交事实并加入后台队列，A 查询状态并打开同项目 B。
4. 同次运行复用 B。桌面持有 B 时，A 的统一 Skill 使用原生消息接口派发封存请求；插件读取 B 的真实新轮次、校验提交和逐文件结果后落盘，A 不代判。
5. 用户在 B 继续追问。重入优先复用历史；归档或确实不存在才创建下一编号，不自动删除或回放旧聊天。

后台独立连接请求只读沙箱；原生 B 可有宿主读写权限，审计守则要求不修改代码。core 和审计 MCP 保持只读，A 维护协同资产。自动物理扫描解析 Python 导入，其他语言关系由 A 维护并标明为申报信息。

## 验证与恢复

本地 103 项测试通过；真实同项目 B 的两轮裁决及归档 B2 已验证。完整桌面强退重启、其他 Codex 版本未实测。当前依赖 CLI 0.153.4 的实验项目协议。领取与宿主发送之间中断时先核对原 B，不能自动重发。

`archguard queue-status` 查看队列；`recover` 回收后台原轮次，桌面派发使用 MCP collect_desktop_audit。确定原轮次终止后可 retry-audit；CLI ask 在后台可恢复 B 时可用，桌面已持有 B 请直接在原生任务追问。单独 Hook 不操纵桌面，原生交接由统一 A Skill 完成。

测试：`python -m pip install -e ".[dev]"`，随后 `python -m pytest -q`。构建：`python scripts/build_release.py`。卸载项目入口：`archguard --project-root <路径> uninstall`，保留历史元数据。

## 文档

- [产品设计 V2.0](docs/PRODUCT_DESIGN_V2.0.md) / [V1.0 历史归档](docs/PRODUCT_DESIGN_V1.0.md)
- [现状审计与交接](docs/HANDOVER.md) / [开发执行计划](docs/DEVELOPMENT_PLAN.md)
- [原 Skill 能力对照](docs/DUAL_SYNC_PARITY.md) / [0.3.0 验收证据](docs/VALIDATION_0.3.0.md)
- [B 复用与历史](docs/B_SESSION_POLICY.md) / [宿主兼容性](docs/HOST_COMPATIBILITY.md)
- [外部项目切换工具](scripts/README.md)

MIT License。
