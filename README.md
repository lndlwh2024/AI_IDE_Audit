# IDE_Audit

> 融合协同记账、代码图谱与独立审计的 AI IDE 插件。

当前版本 **0.3.0a1** 是审计修复预发布版本。79 项自动化测试通过；真实 Codex 合成项目已验证合理/不合理裁决、桌面任务列表可见、原会话追问、服务端恢复及拒绝源码写入。大型项目、完整历史兼容和协同跨步骤事务仍待验收，不能将此版本视作 V2.0 全部完成。

## 核心特性

- **开发与审计分离**：开发端写协同数据，审计端 MCP 仅提供 5 个只读工具。
- **提交证据封存**：需求、账本和图谱申报绑定实际提交，重审不会消费下一轮需求。
- **本地规则引擎**：分析真实 patch、Python 依赖与记账出入，不直接作主观裁决。
- **统一入口**：安装项目守则、MCP 和 Hook；保留已有配置和历史资料。

## 快速开始

```bash
# 从本仓库安装，需要 Python 3.11+、Git；不承诺 PyPI 已发布
git clone https://github.com/lndlwh2024/AI_IDE_Audit.git
cd AI_IDE_Audit
python -m pip install .

# 在目标项目中注册
cd /path/to/your-project
archguard install --ide codex

# 已有 .ai-sync 时，先 migrate --dry-run，再 migrate，最后 install
# Codex 需已登录、信任项目并加载项目级 MCP 配置
```

## 工作原理

1. A 逐条记录原始用户需求，读取并确认协同更新，声明编辑意图，再开发、记账和维护图谱。
2. 只暂存本轮授权文件，使用 `archguard prepare` 封存批次，再提交。也可用 `archguard commit -m "说明" <路径>`。
3. Hook 执行 `archguard audit --notify`；手动 `archguard audit` 只生成本地事实包。证据不足显示 `partial`，不伪造合理结论。
4. `--notify` 通过 Codex app-server 请求独立只读审计，逐文件检查需求相关性。需要可用服务连接和额度；创建 API 会话不等于桌面可见性验收。
5. `archguard recover` 读取原 B 轮次恢复结果；`archguard ask "问题"` 在原会话追问。两者可用 `--audit-id <完整SHA>` 查询旧任务；派发结果不明确时禁止自动重复发送。

无 Hook 时 `archguard commit` 完成本地分析，需要另运行 `audit --notify`。迁移保留源目录和哈希备份，目标已有资产时拒绝覆盖。不要再同时运行独立 dual-agent-sync。

物理图谱自动解析 Python 导入；非 Python 关系和人工职责以单独封存的申报图谱提供给 B，不能冒充已验证的源码事实。B 请求只读沙箱，并禁用其他 MCP、插件和应用连接。已验证测试会话拒绝编辑；更广泛的系统级权限隔离仍需验收。

验证方式：`python -m pip install -e ".[dev]"` 后运行 `python -m pytest -q`。元数据可能包含需求和代码证据，请将 `.ide_audit/` 保持在源码提交之外。

## 文档

- [产品设计文档 V2.0](docs/PRODUCT_DESIGN_V2.0.md)
- [产品设计文档 V1.0（历史归档）](docs/PRODUCT_DESIGN_V1.0.md)
- [现状与交接审计](docs/HANDOVER.md)
- [已确认开发方案与剩余验收计划](docs/DEVELOPMENT_PLAN.md)
- [原 Skill 能力对照](docs/DUAL_SYNC_PARITY.md)

## License

MIT
