# C3b 外网运动预检：未达到运动准入条件

检查时间：2026-10-31 20:17–20:27，中国时间。

本轮用户已确认有人在场看护、工作区清空、人员可操作急停，允许六轴及夹爪测试，关节相对当前姿态的运动不超过 20°且不得超过限位。J7 已确认为夹爪，20°不能直接换算成夹爪的毫米或百分比开合量。

**本轮未发送 SDK connect、关节运动、夹爪、预设、归零或动作序列命令。运动验收未完成。现场许可已确认，但现有系统仍未具备运动准入条件。**

## 实际检查

| 检查 | 结果及边界 |
|---|---|
| Ubuntu | 通过原有 SSH 身份和严格已知主机别名连接 `100.85.63.78`；未添加主机信任或修改认证 |
| PCAN / CAN | PCAN `0c72:000c` 存在，can0 UP、ERROR-ACTIVE、1 Mbps，TX/RX 错误及 bus-off 为 0；RX dropped 累计 38，不能称零丢包 |
| 相机硬件 | XVisio `040e:f408` 存在；原 Vision 服务报告 camera ready 且序号推进 |
| 本地相机源 | 系统级 `thirdhand-stage-camera-source.service` active，PID 28559、NRestarts=0；用户级同名单元不存在，不能把用户级 inactive 误报成相机源已停 |
| 相机发布 | 系统级 publisher 在 activating / auto-restart，观测到 NRestarts=752；近期日志持续有 `MEDIA_GRANT_UNAVAILABLE / response_headers` 约 600 ms 超时、`MEDIA_LEASE_EXPIRED` |
| 云端 | `thirdhand-stage.service`、export、media 三个实际单元均 active；API PID 830563、NRestarts=0；current 为 `/opt/thirdhand-stage/releases/6187bbbe8ec4d5e8` |
| 浏览器 | 正常现有管理员会话读取设备；界面明确显示只允许 SDK 连接和状态读取，真机运动按钮 disabled |
| 连接权 | 本次正常网页申请生成 lease epoch 9，随后因 `browser_stale` 释放；未发送 connect。epoch 8、7 的历史失败仍为 `renewal_unconfirmed` |
| 云端命令 | 最近仍只有此前的 connect completed（17:47:14.114）和 disconnect stopped（17:52:56.587）；没有本轮新增命令 |
| 最终本机 | 20:27:35，sdkConnected=false、connected=false、stateReady=false、moving=false，sourceSequence=723；未残留本轮连接 |

本机实际上下文：

```json
{
  "deviceId": "ee625a57-049a-4c5d-92e1-9578ab9d21c3",
  "executorEpoch": "44fc1f0c-f608-4028-81bc-df1cdb5100d6",
  "readOnly": true,
  "sdkConnected": false,
  "bindingAccepted": true,
  "controlAccepted": true,
  "recordingHealthy": true,
  "videoHealthy": false,
  "sourceSequence": 723
}
```

这里 bindingAccepted / controlAccepted 为 true 是**只读模式**的接入条件，不能解释为实际机械臂运动绑定和视频条件已通过。页面显示 SDK:true 的样本有明确的“历史状态·非实时”标记，采集于 17:47:51.740；不能代替 20:27 的本机 SDK:false。

## 阻断运动的具体条件

1. **部署仍限定只读。** 云端 readiness 只接纳 readOnly 设备，注册身份、设备中继、本机快照均拒绝运动。不能只改一个环境变量或把数据库 control_mode 改成 full 就发送运动。
2. **连接新鲜度未通过。** 此次 browser_stale 与之前 renewal_unconfirmed 均未闭环解决。云端存在 TCP 重传/乱序观察，但还不足以把问题单独归因于校园网，也没有以放宽 500 ms 新鲜度或短租约来隐藏失败。
3. **视频运动准入未通过。** 本地有画面不等于公网观看稳定；camera-only 身份与机械臂 executor 分开，原 raw 流也没有可用于运动准入的可信采集时间。本机 videoHealthy=false。
4. **实际停止能力与物理绑定未验收。** 普通 SDK cleanup/disconnect 的回执不能替代电机实际停止证据；现有 full-mode hardwareAccepted / initialStopVerified 尚未接入真实验证。PCAN 通用序列号也不能单独证明机械臂身份。
5. **运动目标尚不能生成。** 需要新的六轴实测起点、设备一致的限位与路径检查。旧样本 J2=-12.21°，而仓库默认 J2 下限=-12°；应核对设备坐标/限位，不能扩大限位、直接夹紧到边界或把历史姿态作为往返终点。夹爪另需明确 mm/% 的测试量及其有效范围。

## 后续执行顺序

- 先解决持续连接与媒体授权故障，以当前安全时限复测；稳定观看与实际故障恢复均需新证据。
- 将可信帧采集时间、当前操作者实际解码帧和机械臂 executor 绑定，继续保留失去视频/授权时拒绝新动作。
- 完成现场设备绑定、停止/失联保护和限位坐标核验；形成可审阅的具体部署差异、测试配置及回退，不解除既有门禁代替实现。
- 通过正常管理员 MFA 会话连接，读取新的起始姿态；先做小幅低速试验，再在已获准的 20°上限内评估六轴协同，夹爪按明确的开合量验收。不自动 Home/Zero，不重复发送结果未知的动作。
- 核对实际轨迹、停止回执和 PostgreSQL 原始记录；退出后检查 SDK 断开和控制权释放。

本轮仅记录预检，没有更改运行代码、服务配置、身份权限、数据库结构、公共端口或机械臂限位；没有 Git commit / push。截图保存在本任务忽略证据目录 `evidence/C3b-read-only-motion-blocked.png`。
