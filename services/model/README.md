# Model Service

状态：**仅规划脚手架，尚未加入 launcher。**

本目录将提供统一模型推理服务，隔离 VLA、ACT 和 Diffusion Policy 的运行环境、checkpoint 与设备需求。上层只依赖稳定请求/响应协议，不直接导入具体模型实现。

子目录：

- `vla/`：视觉语言动作模型适配；
- `act/`：ACT 策略适配；
- `diffusion_policy/`：Diffusion Policy 适配。

模型输出必须被标记为候选动作或轨迹，不能直接发送 CAN 帧。模型权重放在 `local/models/`，其清单、哈希、许可证和兼容性信息由项目资产工具管理。

迁移任务见 [`../../docs/MIGRATION_BACKLOG.md`](../../docs/MIGRATION_BACKLOG.md)。
