# IDE_Audit 0.4.8

安装 Codex 插件后，每个项目仍默认关闭。用户明确说“为当前项目开启 IDE_Audit”后，A 使用统一 Skill 完成项目接入；也可运行 `python scripts/install.py --project-root <项目路径> --consent`。需要 Python 3.11+、Git、已登录的 Codex 桌面与 CLI，首次安装依赖需要网络。

启动提示依赖用户在 Codex 信任本插件 Hook；未信任时不自动运行，也不自动开启项目。支持手动开启，明确拒绝后不重复询问。

A 首次或恢复接入先更新图谱和代码同步；提交后 B 使用现有 Codex 大模型在同项目审计。同次运行复用 B；重入优先恢复，归档或确实丢失后新建下一编号。完整桌面退出重启尚未实测。

A/B 任意窗口均可暂停，保留全部资产。恢复只能由 A 完成同步；暂停期间提交不自动逐次补审。B token 用量通过 get_token_usage 查询，未知不填零。宿主在途轮次可能仍完成收尾。

卸载项目入口：`.ide_audit/runtime/Scripts/python.exe -m archguard.cli.main --project-root <项目路径> uninstall`。历史保留。旧项目迁移工具单独发行，不包含在插件中。尚未发布公共插件市场。
