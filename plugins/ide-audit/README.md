# IDE_Audit Codex 插件

在 Codex 中加载本目录的插件后，调用 ide-audit Skill 接入当前项目。也可执行 `python scripts/install.py --project-root <项目路径>` 完成项目 MCP、统一守则及 Hook 安装。

要求：Python 3.11+、Git、已登录的 Codex Windows 桌面与 CLI；当前已验证 CLI 0.153.4 的实验项目协议。首次安装依赖需要网络。创建 B 使用现有 Codex 账户，按账户额度运行。

A 每次接入先更新图谱，再执行协同开发。提交后 Hook 后台派发同项目 B，A 的统一 Skill 使用桌面内置导航打开 B。正常重启复用原 B；归档或删除后新建，不回放旧聊天。

卸载项目入口：使用 `.ide_audit/runtime/Scripts/python.exe -m archguard.cli.main --project-root <项目路径> uninstall`。历史报告和协同资产保留。

旧项目迁移工具单独交付，不包含在本插件中。
