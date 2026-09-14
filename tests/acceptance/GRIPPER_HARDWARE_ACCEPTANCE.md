# Startouch Gripper Hardware Acceptance

状态：未授权、未执行。此文件是操作员清单，不是自动测试脚本。

## Allowed Physical Scope

```text
One open command and one close command, with no object between the fingers,
no arm-joint target, no automatic retry, and hardware emergency stop reachable.
```

任何扩大范围的动作都需要新的计划和批准。页面“软件停止”依赖完整软件与 CAN 链路，不能替代独立硬件急停或物理断电。

## Evidence Before Approval

- [ ] 全量 Node、Python 和隔离端到端模拟测试通过。
- [ ] 当前分支和未提交修改已记录，没有切换、合并或推送。
- [ ] 3000、3004、3100、3200、9983 的进程所有权已记录。
- [ ] 当前在线外部服务已按单独批准安全停止，并由 Launcher 唯一接管。
- [ ] `can0` 为 UP、1,000,000 bit/s，且正在接收六个电机反馈。
- [ ] Robot health 显示 `connected:true`、`stateReady:true`、`moving:false`、状态不超过 500 ms。
- [ ] 夹爪内无物体，机械臂工作区无人员和障碍物。
- [ ] 物理急停或断电装置可立即触达。

批准人：________________  时间：________________

## Open Command

- [ ] 记录命令前 J1-J6 与夹爪位置。
- [ ] 页面显示目标 100%、计划 ID、版本、摘要和夹伤风险。
- [ ] 确认前夹爪和六关节均未运动。
- [ ] 单击确认一次；日志仅出现一个 primitive ID。
- [ ] 实际夹爪反馈与 100% 的误差不超过 2%。
- [ ] 任一机械臂关节变化不超过 0.5°。
- [ ] 没有自动重试；重复确认被拒绝。

结果：________________  证据文件：________________

## Close Command

- [ ] 再次确认夹爪内无物体。
- [ ] 记录命令前 J1-J6 与夹爪位置。
- [ ] 页面显示目标 0%、计划 ID、版本、摘要和夹伤风险。
- [ ] 单击确认一次；日志仅出现一个新 primitive ID。
- [ ] 实际夹爪反馈与 0% 的误差不超过 2%。
- [ ] 任一机械臂关节变化不超过 0.5°。
- [ ] 没有自动重试；授权重放被拒绝。

结果：________________  证据文件：________________

## Stop and Redaction

- [ ] 在非运动状态点击软件停止，页面仍明确说明它不是硬件急停。
- [ ] 保存已脱敏日志：ID、时间戳、目标、实际反馈、关节偏移与结果。
- [ ] 日志和截图不包含 `robot-execution.token` 的内容。

出现意外机械臂运动、陈旧状态、反馈缺失、令牌错误、重复命令或不确定结果时立即判定失败。先请求软件停止；若不能确认停止，操作员立即使用硬件急停或物理断电。
