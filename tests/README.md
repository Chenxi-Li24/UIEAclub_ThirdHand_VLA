# Tests

`tests/` 按语言和测试范围组织，默认测试不得连接真实机械臂或发送 CAN 控制帧。

| 路径 | 覆盖范围 |
|---|---|
| `node/` | launcher、Web Gateway、Robot Service 的 Node 测试 |
| `python/` | Robot Python 桥、Vision Service 与资产工具测试 |
| `unit/` | 仓库布局、平台契约和其他纯单元测试 |
| `integration/` | 跨模块但仍应可安全离线运行的集成测试 |
| `acceptance/` | 需要操作员逐项签署的真机验收清单；默认不自动执行 |

常用命令：

```bash
npm run test:node
npm run test:python
python -m pytest tests/integration/test_authorized_gripper_chain.py -v
python -m pytest tests/unit/platform/test_repository_layout.py -q
```

真机验证必须单独标识，执行前确认机械臂工作区安全、硬件急停可触达、`can0` 所有权唯一，并获得本次动作授权。

`test_authorized_gripper_chain.py` 会启动临时端口上的 Startouch 模拟桥、Robot、Orchestrator 和 Web Gateway。它不打开 `can0`，并覆盖授权前零动作、一次性授权、双击/重放、过期/篡改、断线、陈旧/运动状态、反馈超时和意外关节偏移。
