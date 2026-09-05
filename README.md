# IDE_Audit

> AI IDE 架构审计插件 — 防止 AI 自作主张变更架构

IDE_Audit 是一个独立的 AI IDE 架构审计工具。它在 AI IDE（如 Codex、Cursor 等）完成每轮开发后，自动检测代码变更是否超出用户需求范围，特别是在架构层面（模块合并/拆分、接口增删、数据库变更等）。

## 核心特性

- **双窗口分离审计**：开发窗口和审计窗口物理隔离，保证审计独立性
- **无需额外 LLM 配置**：复用 AI IDE 自带的 LLM，零配置
- **本地规则引擎**：确定性的架构变更检测，不依赖 LLM
- **一键安装**：`archguard install --ide codex` 自动注册 MCP + Skill + Hook

## 快速开始

```bash
# 安装
pip install ide-audit

# 在目标项目中注册
cd /path/to/your-project
archguard install --ide codex

# 然后正常使用 AI IDE 开发，审计自动触发
```

## 工作原理

1. 用户在 AI IDE（A 窗口）发送需求，AI 正常编码
2. AI 完成 commit 后，post-commit hook 触发 IDE_Audit
3. IDE_Audit 本地引擎执行 git diff + 规则引擎分析（不调用 LLM）
4. 自动打开 AI IDE 新窗口（B 窗口），审计 AI 在全新上下文中判断变更合理性
5. B 窗口展示审计报告

## 文档

- [产品设计文档 V2.0](docs/PRODUCT_DESIGN_V2.0.md)
- [产品设计文档 V1.0（历史归档）](docs/PRODUCT_DESIGN_V1.0.md)

## License

MIT
