# IMPLEMENTATION GATE

状态：**研究与安全核心实现允许；真实执行禁止**  
日期：2026-08-04

## 已完成前置条件

- [x] 只读审计 Ubuntu、运行服务、端口、CAN 锁、USB、GPU、版本、git dirty state。
- [x] 读取近期 Claude 会话和历史 handover，不修改其记录。
- [x] 审查现有视觉、标定、追踪、代理状态机和前端消息路径。
- [x] 检索论文、官方文档/仓库、issues 与社区经验，并区分证据等级。
- [x] 比较 A/B/C 架构、资源、许可、风险与迁移路径。
- [x] 定义离线 benchmark、接受门限和 fail-closed 规则。

## 允许的实现范围

- 新建隔离 git worktree/分支；复制但不改动原 dirty worktree。
- 新增纯 Python 类型、SE(3)/RPY、SEUCM、深度注册、追踪/对象记忆、安全 gate、录制 manifest。
- 新增 pytest、合成 fixture、离线 benchmark 和文档。
- 新增 Dry Run JSON 生成器；不得导入/调用 Startouch 执行 API。
- 只读查询进程、HTTP 状态和硬件信息。

## 禁止项

- 不发送机械臂或夹爪命令，不调用现有 WebSocket 控制路径。
- 不启动第二个 CAN/Startouch 实例，不释放或抢占现有锁。
- 不重启/停止现有 3000、8085、8766 或相机进程。
- 不修改 `.env`、udev、sysfs、USB autosuspend、系统服务或网络配置。
- 不覆盖任何现有标定 JSON/图像；新标定也必须版本化。
- 不把旧 D435/Lumos 外参标记为 valid。
- 不启用真实 `RobotExecutor`，不修复 Grasp 按钮到真实后端。

## 代码合并 gate

- 新核心模块不依赖硬件即可 import 和测试。
- 所有变换命名含 `target_from_source`，单位显式。
- 关键数据含 monotonic timestamp、frame id、calibration id 和 validity。
- stale/ambiguous/invalid calibration 默认拒绝。
- 原工作树 `git status` 和运行服务 PID/端口保持不变（新增隔离 worktree 除外）。

## 实机 gate（本轮不得跨越）

完成 `07_CALIBRATION_PLAN.md`、`13_BENCHMARK_AND_ACCEPTANCE_PLAN.md` 的标定/回放门限后，由用户现场确认，另开明确授权。未获得该授权时，任何实现都必须停在 Dry Run。

