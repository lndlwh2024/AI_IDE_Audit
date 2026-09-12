# AGENTS.md — IDE_Audit 项目协作规则

> 2026-09-10 实施规则：当前 0.4.2。项目逐项明确授权后才工作，A/B 可暂停和请求恢复，只有 A 更新图谱及同步后开启。B 使用同项目原生 Codex 大模型，允许宿主读写权限但审计不修改源码；审计 MCP 的控制/用量工具可写元数据，不提供 A 的图谱/源码维护工具。旧 Skill 逻辑已融合；NEWS 单向迁移在插件之外，无迁移回滚流程。下文早期“绝对无写权限/只读 MCP”等描述以此条、PRODUCT_DESIGN_V2.0 和 HANDOVER 当前结论为准。


## 1. 项目概述

**IDE_Audit** 是一个 AI IDE 架构审计插件，在 AI IDE 完成每轮开发后，通过**用户原始需求 + git diff** 自动判断变更是否合理，防止 AI 自作主张修改架构。

- **仓库地址**：https://github.com/lndlwh2024/AI_IDE_Audit
- **工作目录**：H:\AIcode\Antigravity\AI_IDE_Audit
- **技术栈**：Python 3.11+, pip + pyproject.toml, Click, MCP SDK, gitpython, Jinja2, Pydantic, httpx, pytest
- **首个适配**：Codex Windows 桌面版（ChatGPT desktop app，Powered by Codex & OWL）
- **开源协议**：MIT

## 2. 核心架构与两阶段工作机制

IDE_Audit 采用"同一 AI IDE，双窗口分离审计 + 双系统融合"架构：
- **A 窗口（开发）**：用户正常开发，维护 `dual-agent-sync` 代码图谱与操作记账本，Skill 自动捕获两次 commit 间的全部用户提示词，修改完毕后自动执行 `git commit`。
- **阶段一：IDE Audit Server（本地物理与图谱分析，只读）**：
  - 提取最高权重物理事实（Git Diff `HEAD~1..HEAD`）；
  - 结合 `codegraph/graph.json` 与规则引擎扫描架构/模型层「是否有变更」及受影响节点依赖边；
  - 结合 `collab/ledger.jsonl` 核验实际 Diff 与记账本的完整出入清单（未声明偷改、虚报、范围出入）；
  - 输出客观分析报告包，**不作主观越权判断**。
- **阶段二：B 窗口（原生独立审计会话，双尺度研判与答疑）**：
  - commit 后通过 `codex app-server` API 自动拉起或复用独立审计会话（无开发记忆）；
  - 接收阶段一客观事实包、用户原始需求、代码图谱与记账申报；
  - **双尺度裁决（架构合理性 + 文件强相关性）**：
    - 宏观：架构/模型变更是否在需求授权范围内；
    - 微观：每个改动文件是否与需求强相关（**即便架构合理，改动了无关文件也判定为不合理**）；
    - 出入：结合出入清单核查未声明修改。
  - **权限与交互答疑**：用户接受原生 B 的宿主读写权限，审计守则要求只读核查；插件 core/审计 MCP 不修改业务代码，输出结构化报告后会话保持存活，支持用户继续追问答疑。
- 支持自动触发（post-commit hook）和手动触发（`archguard audit`），审计范围始终严格限定为最后一次 commit（HEAD~1..HEAD）。

## 3. 项目文档

| 文档 | 路径 | 说明 |
|:---|:---|:---|
| 产品设计文档（V2.0 终局融合版） | `docs/PRODUCT_DESIGN_V2.0.md` | 完整的产品设计、技术架构、审计流程、四阶段计划（含 dual-agent-sync 整合） |
| 产品设计文档（V1.0 历史归档） | `docs/PRODUCT_DESIGN_V1.0.md` | V1.0 历史版本，保留不改 |
| 本文件 | `AGENTS.md` | 项目协作规则 |
| 当前交接与审计 | `docs/HANDOVER.md` | 当前实现、修复前基线及未完成验收项 |
| 开发执行计划 | `docs/DEVELOPMENT_PLAN.md` | 已确认方案、实施进度和后续验收门 |
| 原 Skill 能力对照 | `docs/DUAL_SYNC_PARITY.md` | 完整继承目标的证据与剩余差距 |

## 3.1 核心架构分工边界

- `archguard/sync/`：负责数据的**写入与维护**（由 A 窗口 MCP 工具调用），继承 dual-agent-sync 100% 功能
- `archguard/core/`：负责数据的**只读分析与扫描**（由审计引擎调用），不修改任何文件
- `archguard/runtime.py` / `archguard/storage.py`：负责封存提交证据及持久化结果，不将写入放回只读 core；完整继承是验收目标，不以模块存在宣称已完成。

## 4. 开发约定

- 所有回复、注释使用简体中文，代码标识符保持英文
- 代码编写完毕后给出功能审计清单
- 使用 GitHub 统一部署发布
- 每次 git push 成功后提示版本号和变更内容

## 5. 开发阶段（4 个阶段）

2026-09-09 当前实施版为 `0.3.0`：103 项测试通过，真实同项目原生 B 连续裁决、归档新编号已验证。全桌面强退重启和其他宿主版本未实测。以下阶段划分保留作路线图，旧版本的完成标记不能代替当前 HANDOVER 的证据。

### 阶段一：核心物理审计引擎（✅ 已完成，v0.1.0）
- `archguard/core/` — 审计主引擎、Diff 分析、架构规则检测、需求存储、报告生成（27个测试全通，已发布GitHub）
- `archguard/rules/` — 固定审计规则库（9大检测维度）

### 阶段二：CodeGraph 架构图谱与记账出入核验
- `archguard/core/graph_analyzer.py` — 代码图谱拓扑解析与依赖变动分析
- `archguard/core/ledger_analyzer.py` — 记账本与 Diff 出入核验
- `archguard/core/engine.py` — 升级主引擎编排客观分析包

### 阶段三：MCP Server + Codex 桌面版适配
- `archguard/mcp/` — 只读 MCP Server 实现
- `archguard/adapters/codex/` — Codex 桌面版会话管理（app-server API）与双端 Skill 模板

### 阶段四：CLI + 全场景测试 + 文档
- `archguard/cli/` — CLI 完整命令矩阵
- `tests/` — 端到端集成测试与交付文档

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
