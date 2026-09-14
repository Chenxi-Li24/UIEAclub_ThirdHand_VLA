# 现有代码审查

## 严重级别说明

- P0：可能产生错误实体动作或不可控状态推进。
- P1：会使三维定位、标定或跟踪结果系统性错误。
- P2：可靠性、可维护性或性能问题。

## P0 问题

### 抓取状态机没有命令关联

`web-control/server/proxy.js:473-586` 中 hover、descend、close、lift、home、open 依靠全局阶段推进。`command_complete` 监听器没有匹配期望 `request_id`；`go_home` 和夹爪命令甚至不携带 request id。`startouch_bridge.py` 的夹爪完成消息也没有该字段。

后果：无关的手动命令完成、被拒绝命令后的迟到事件，甚至 `reached=false` 的夹爪超时，都可能推进抓取流程。状态机还缺少阶段 deadline、错误终止、断连终止和幂等复位。

修复门禁：所有动作必须由 `operation_id + step_id` 关联；仅接受当前步骤、成功且时间窗口内的完成事件；错误、超时、断连立即进入 `ABORTED`，且后续事件不能复活。

### 在线服务不是 Dry Run

`.env` 中 `STARTOUCH_DRY_RUN=0`。视觉开发不能通过现有 3000 服务验证“按钮是否工作”，因为任何修复后的消息可能触发真实动作。必须先建立与执行器物理隔离的离线控制面或显式 Dry Run 服务。

## P1 问题

### RPY 被误作 Rodrigues 旋转向量

以下代码调用 `cv2.Rodrigues(np.array(euler))`：

- `camera_bridge.py:129-134`
- `d435_grasp.py:140-145`
- `d435_calibrate.py:153-158`
- `d435_validate.py:97-102`
- `handeye_calib.py:337-343`

Startouch SDK 返回的是 roll/pitch/yaw，SDK C++ 运动学定义为 `Rz(yaw) * Ry(pitch) * Rx(roll)`。Rodrigues 输入则是轴角旋转向量。离线数值验证：RPY `[0.3,-0.4,1.0]` 产生 13.82° 差异，`[1.2,0.8,-0.6]` 产生 31.46° 差异。

### D435 实测深度在主路径被忽略

`camera_bridge.py:148-189` 虽接收 bbox，却没有使用 bbox 边界。只要射线向下，就与 `DESK_Z` 平面相交并立即返回；仅在射线不向下时才读取中心像素深度。

后果：返回的是桌面交点而非物体表面，`bz` 在不同分支分别表示固定桌面高度和实测三维 Z，字段语义不一致。已有 `bbox_depth()` 辅助函数未被调用。

### 深度被当成射线欧氏距离

回退路径先归一化 `[xn, yn, 1]`，再乘 RealSense depth。RealSense 对齐深度是光轴 Z，正确反投影应为 `[xn*z, yn*z, z]`。现有代码会对离中心像素产生系统性缩短和 Z 偏差。

### 手眼标定实现与输出不可信

`d435_calibrate.py` 同时存在 RPY 错误、自定义 Tsai 相对运动方程错误、结果重复反转，并将方法错误标注为 OpenCV Tsai。`d435_validate.py` 使用相同错误变换自洽验证，不能发现系统偏差。D435 外参平移范数约 0.387 m，与物理安装尺度可疑。

Lumos 标定仍用针孔/不匹配的 omnidir 近似处理 SEUCM 220° 图像，RMS 107.95 px 已判定失败。

### 跟踪器在漏检时立即删除所有对象

`camera_bridge.py:93-125` 为单帧贪心 IoU > 0.3：无 Kalman、Hungarian、类别门控、外观特征、track age 和 missed count；检测帧为空时立刻清空。检测只在每 10 帧运行，其他帧 bbox 与三维坐标保持陈旧。

## P2 问题

- 无统一相机帧数据结构、时间戳域、帧号、单位、坐标系和有效性字段。
- `SAFE_Z` 被声明但未使用。
- `latest_arm_ts` 存在但不检查机械臂状态新鲜度。
- 无 RGB/depth 时间差、机械臂是否静止、外参版本、深度覆盖率和遮挡标记。
- `camera-bridge.js` 每次启动自动 sudo 写 USB power/autosuspend，属于隐式系统状态修改。
- `lumos_stream.py` 探测 `[1,0]` 设备索引，未绑定 by-id；多摄像头环境容易打开错误节点。
- `proxy.js` 注释了 Lumos 子进程启动，但系统仍有孤立进程，运行所有权不清。
- `/tmp/proxy3000.log` 以约 10 Hz 持续记录关节，日志噪音和磁盘增长不可控。
- 当前测试只覆盖旧 fixed-pick-place demo，不覆盖相机模型、深度融合、坐标变换、跟踪和状态机。

## 审查决策

不在现有大文件中继续叠加功能。先新增纯函数/不可变数据结构与离线测试，再以适配器接入旧 bridge。旧的抓取执行路径默认保持禁用；只有相机、标定、融合、稳定度和 Dry Run 门禁全部通过后，才允许人工审核一次候选动作。
