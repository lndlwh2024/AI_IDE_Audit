# AGENTS.md — IDE_Audit 项目协作规则

## 1. 项目概述

**IDE_Audit** 是一个 AI IDE 架构审计插件，在 AI IDE 完成每轮开发后，通过**用户原始需求 + git diff** 自动判断变更是否合理，防止 AI 自作主张修改架构。

- **仓库地址**：https://github.com/lndlwh2024/AI_IDE_Audit
- **工作目录**：H:\AIcode\Antigravity\AI_IDE_Audit
- **技术栈**：Python 3.11+, pip + pyproject.toml, Click, MCP SDK, gitpython, Jinja2, Pydantic, httpx, pytest
- **首个适配**：Codex Windows 桌面版（ChatGPT desktop app，Powered by Codex & OWL）
- **开源协议**：MIT

## 2. 核心架构与裁决逻辑

IDE_Audit 采用"同一 AI IDE，双窗口分离审计"架构：
- **A 窗口（开发）**：用户正常开发，Skill 自动捕获 prompt（两次 commit 间的全部用户提示词）。
- **IDE Audit Server（本地 MCP 服务）**：负责提取物理事实（Git Diff）、运行确定性规则引擎扫描 9 大架构变更信号。输出客观物理事实，不作语义越权判断，结果不可被篡改。
- **B 窗口（审计与最终裁决）**：commit 后通过 `codex app-server` API 自动创建/复用独立审计会话（无开发记忆）。直接继承 IDE Audit Server 的物理客观结果，并由 LLM 负责需求与代码实现的语义一致性审计。
- **一票否决裁决制**：物理检测合规且语义范围合理才判定通过；任一项不合规即判定不通过。无论是否通过，均必须输出完整的变更资源清单与详细原因。
- 支持自动触发（post-commit hook）和手动触发（`archguard audit`），审计范围始终严格限定为最后一次 commit（HEAD~1..HEAD）。

## 3. 项目文档

| 文档 | 路径 | 说明 |
|:---|:---|:---|
| 产品设计文档 | `docs/PRODUCT_DESIGN.md` | 完整的可行性分析、技术架构、审计流程、开发计划 |
| 技术架构文档 | `docs/ARCHITECTURE.md` | 技术架构细节 |
| 本文件 | `AGENTS.md` | 项目协作规则 |

## 4. 开发约定

- 所有回复、注释使用简体中文，代码标识符保持英文
- 代码编写完毕后给出功能审计清单
- 使用 GitHub 统一部署发布
- 每次 git push 成功后提示版本号和变更内容

## 5. 开发阶段

### 阶段一：核心引擎（当前）
- `archguard/core/` — 审计主引擎、Diff 分析、架构检测、需求存储、报告生成
- `archguard/rules/` — 固定审计规则库

### 阶段二：MCP Server + Codex 桌面版适配
- `archguard/mcp/` — MCP Server 实现
- `archguard/adapters/codex/` — Codex 桌面版适配（含 codex app-server 会话管理）

### 阶段三：CLI + 测试 + 文档
- `archguard/cli/` — CLI 工具
- `tests/` — 单元测试

## 6. 目录结构

```
AI_IDE_Audit/
├── archguard/                     # Python 包
│   ├── core/                      # 核心引擎（不调用 LLM）
│   │   ├── engine.py              # 审计主引擎
│   │   ├── diff_analyzer.py       # Git Diff 解析
│   │   ├── architecture_detector.py  # 架构变更检测
│   │   ├── prompt_store.py        # 需求存储
│   │   └── report_generator.py    # 报告生成
│   ├── rules/                     # 审计规则
│   ├── mcp/                       # MCP Server
│   ├── adapters/                  # IDE 适配层
│   │   ├── __init__.py
│   │   ├── codex/                 # Codex 桌面版适配
│   │   │   ├── __init__.py
│   │   │   ├── installer.py       # 一键安装
│   │   │   ├── session_manager.py # B 窗口会话管理（codex app-server API）
│   │   │   ├── skill_template.md  # A 窗口 Skill 模板
│   │   │   └── audit_prompt.md    # B 窗口审计 prompt 模板
│   │   └── git_hook.py            # Git Hook 管理
│   ├── cli/                       # CLI 工具
│   └── config/                    # 配置
├── templates/                     # 模板文件
├── tests/                         # 测试
├── docs/                          # 文档
├── pyproject.toml
├── README.md
└── LICENSE
```

## 7. 命令执行

- 安全的只读命令可直接运行
- 破坏性命令需用户确认
- 所有命令在 `H:\AIcode\Antigravity\AI_IDE_Audit` 下执行
