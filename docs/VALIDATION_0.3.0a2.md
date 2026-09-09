# 0.3.0a2 本地验收记录

日期：2026-09-09。环境沿用 0.3.0a1 的 Python 3.12 / MCP 2.2。

完整回归：91 passed，41.83 秒。命令为 `.venv/Scripts/python.exe -m pytest -q -p no:cacheprovider --basetemp=.venv/clarification-fixed --junitxml=.ide_audit/clarification-tests.xml`。

功能审计清单：

- [x] 旧项目资产迁移移出 archguard；CLI 无 migrate 命令，安装不读取旧账本。外部脚本原备份/回滚测试继续通过。
- [x] A 首次接入建立图谱，再次接入更新节点；解析失败保留原图谱并阻止 begin_edit。
- [x] 长编辑显式续期；他人或过期租约不能续期。
- [x] B 恢复时校验工作目录；明确归档或丢失时新建，保留替代关系，不回放聊天、不取消原归档。
- [x] 权限、网络及未加载错误不重建 B。
- [x] 修复首次创建 OS 锁时占位字节写入的并发竞争，线程和进程记账回归通过。
- [x] wheel 资源和边界检查通过；清除旧 build/lib 中残留的迁移模块后重建。
- [ ] 同桌面 projectId 归属尚未实现；本轮 B 生命周期是协议模拟回归，不能代替同项目真实桌面验收。
- [ ] 未关闭整个 Codex 桌面验证重启；未执行 NEWS 迁移。
- [ ] 完整增量扫描、目录意图锁、跨步骤事务与忙碌队列仍待开发。

构建文件：`.venv/clarification-wheel/ide_audit-0.3.0a2-py3-none-any.whl`。
SHA256：`792919b12098986868d6ae2aee152ad6bbd1d79f24f294f8f336c64be78b2d9d`。

本版本不代表全部开发任务已完成，也不是稳定版或 PyPI 发布。
