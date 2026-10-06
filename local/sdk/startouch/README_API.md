# StarTouch Python SDK API

Current SDK version: `0.1.7`.

Version note: `2026-06-05`, author `Charlie`.

当前 SDK 版本：`0.1.7`。

版本说明：`2026-06-05`，作者 `Charlie`。

Important release behavior changes are recorded in `CHANGELOG.md`.

重要版本行为变化记录在 `CHANGELOG.md`。

You can query it from Python:

可以在 Python 中查询：

```python
import startouch
from startouchclass import __version__

print(startouch.__version__)
print(__version__)
```

This document summarizes the public Python APIs exposed by
`interface_py/startouchclass.py`. Joint angles and Euler angles are in radians.
Cartesian positions and gripper distances are in meters.

本文档总结 `interface_py/startouchclass.py` 暴露给用户的公开 Python API。
关节角和欧拉角单位为弧度；笛卡尔位置和夹爪距离单位为米。

## Initialization

```python
from startouchclass import SingleArm, MotionProgram

arm = SingleArm(can_interface_="can0", gripper=True, enable_fd_=False)
```

Arguments:

- `can_interface_`: CAN interface name, for example `"can0"`.
- `gripper`: whether the gripper exists and should be enabled.
- `enable_fd_`: whether to enable CAN FD. The verified path currently uses
  `False`.

参数：

- `can_interface_`：CAN 口名称，例如 `"can0"`。
- `gripper`：是否存在并启用夹爪。
- `enable_fd_`：是否启用 CAN FD。目前已验证路径使用 `False`。

Release resources after use:

使用结束后释放资源：

```python
arm.cleanup()
```

## Public Gripper APIs

## 公开夹爪接口

### `setGripperPosition(position)`

Set gripper opening by normalized position.

按归一化开合比例控制夹爪。

```python
arm.setGripperPosition(1.0)  # fully open
arm.setGripperPosition(0.0)  # fully closed
```

- `position`: normalized opening ratio, typically `0.0 ~ 1.0`.
- `0.0`: closed.
- `1.0`: open to max distance.

- `position`：归一化开合比例，通常为 `0.0 ~ 1.0`。
- `0.0`：闭合。
- `1.0`：打开到最大距离。

The lower layer clamps the value to `[0, 1]` and maps it to
`position * gripper_dis_max`.

底层会将该值限制到 `[0, 1]`，再映射为 `position * gripper_dis_max`。

### `setGripperDistance(distance, kp=None, kd=None)`

Set gripper opening by physical distance.

按物理距离控制夹爪开合。

```python
arm.setGripperDistance(0.085)
arm.setGripperDistance(0.0, 10, 0.5)
```

- `distance`: gripper opening distance in meters, normally `0.0 ~ 0.085`.
- `kp`: optional gripper control stiffness.
- `kd`: optional gripper control damping.

- `distance`：夹爪开合距离，单位米，通常为 `0.0 ~ 0.085`。
- `kp`：可选夹爪控制刚度。
- `kd`：可选夹爪控制阻尼。

The lower layer clamps the distance to the valid gripper range.

底层会将距离限制在有效夹爪行程内。

### `setGripperDistance_raw(distance, kp=8.0, kd=0.1)`

Currently this Python wrapper calls `setGripperDistance(distance, kp, kd)`.

当前 Python 包装层会调用 `setGripperDistance(distance, kp, kd)`。

### `get_gripper_position()` / `get_gripper_distance()`

Read normalized gripper opening or physical opening distance.

读取归一化夹爪开度或物理开合距离。

```python
g = arm.get_gripper_position()
d = arm.get_gripper_distance()
```

### `openGripper()` / `closeGripper()`

Convenience APIs for opening and closing the gripper.

打开或闭合夹爪的便捷接口。

```python
arm.openGripper()
arm.closeGripper()
```

Low-level gripper passthrough is not exposed in the public Python interface.
Use `setGripperPosition()` or `setGripperDistance()` instead.

低层夹爪透传接口不在公开 Python 接口中暴露。请使用 `setGripperPosition()` 或
`setGripperDistance()`。

## Joint State APIs

## 关节状态接口

### `get_joint_positions()` / `get_joint_velocities()` / `get_joint_torques()`

Read current joint positions, velocities, or torques.

读取当前关节位置、速度或力矩。

```python
q = arm.get_joint_positions()
dq = arm.get_joint_velocities()
tau = arm.get_joint_torques()
```

`q` and `dq` have shape `(6,)`; positions are radians and velocities are
radians per second.

`q` 和 `dq` 形状为 `(6,)`；位置单位为弧度，速度单位为弧度每秒。

## Recommended Joint Motion APIs

## 推荐关节运动接口

### `set_joint_waypoints(waypoints, time_sec=None, speed_percent=None)`

Preferred API for joint trajectory replay, VLA deployment, and batched waypoint
execution. `move_joint_waypoints(...)` is kept as a compatibility alias.

推荐用于关节轨迹复现、VLA 部署和批量路点执行。`move_joint_waypoints(...)`
作为兼容旧代码的别名保留。

```python
waypoints = [
    [0, 0.1, -0.3, 0.4, 0, 0],
    [0, 0.2, -0.5, 0.6, 0, 0],
]

# Time mode: recommended for timestamped trajectory replay.
duration = arm.set_joint_waypoints(waypoints, time_sec=2.0)

# Speed mode: normalized speed ratio.
duration = arm.set_joint_waypoints(waypoints, speed_percent=0.2)

# Default mode: equivalent to speed_percent=0.1.
duration = arm.set_joint_waypoints(waypoints)
```

```python
# 时间模式：推荐用于带严格时间戳的轨迹复现。
duration = arm.set_joint_waypoints(waypoints, time_sec=2.0)

# 速度模式：归一化速度比例。
duration = arm.set_joint_waypoints(waypoints, speed_percent=0.2)

# 默认模式：等价于 speed_percent=0.1。
duration = arm.set_joint_waypoints(waypoints)
```

Parameter rules:

- Pass only `time_sec` or only `speed_percent`.
- If both are provided and positive, Python raises `ValueError`.
- If neither is provided, the wrapper sends `speed_percent=0.1`.
- `time_sec` is the requested duration for the whole waypoint trajectory.
- `speed_percent` is a normalized velocity ratio in `(0, 1]`.

参数规则：

- 只能传 `time_sec` 或 `speed_percent` 其中一个。
- 如果两个都传且都为正数，Python 会抛出 `ValueError`。
- 如果两个都不传，包装层会按 `speed_percent=0.1` 下发。
- `time_sec` 是整段路点轨迹的总时长。
- `speed_percent` 是 `(0, 1]` 内的归一化速度比例。

Implementation:

- The current joint state is prepended as the trajectory start.
- All target waypoints are clamped to URDF joint limits.
- Consecutive duplicate points are compacted.
- Each segment uses quintic Hermite interpolation. Interior tangents are
  estimated from neighboring segments, and endpoints start/end with zero
  velocity and acceleration.
- Samples are generated at the internal motion frequency, currently `400 Hz`.
- Speed mode scales `joint_trajectory.max_vel_limits` by `speed_percent`.
- Time mode distributes `time_sec` across all waypoint segments and checks
  trajectory limits according to config.
- The call blocks until the whole waypoint trajectory finishes, an emergency
  stop happens, or controller cleanup/exiting interrupts the motion.

实现逻辑：

- 底层会把当前关节状态作为轨迹起点。
- 所有目标路点会按 URDF 关节限位裁剪。
- 连续重复点会被合并。
- 每段使用五次 Hermite 插值；中间点切向量由相邻段估计，首末端速度和加速度为零。
- 轨迹按内部运动频率采样，目前为 `400 Hz`。
- 速度模式会用 `speed_percent` 缩放 `joint_trajectory.max_vel_limits`。
- 时间模式会把 `time_sec` 分配到所有路点段，并按配置检查轨迹限制。
- 该调用会阻塞，直到整段路点轨迹完成、触发急停，或控制器 cleanup/退出导致中断。

### `set_joint(positions, tf=2.0)`

Move to one joint target with one start-stop planned segment.

移动到单个关节目标点；底层会生成一段启停轨迹。

```python
arm.set_joint([0, 0.2, -0.4, 0.5, 0, 0], tf=3.0)
```

Implementation:

- `set_joint()` sets one target only.
- The control loop runs at `400 Hz`.
- The trajectory uses a seventh-order smoothstep polynomial:
  `35*s^4 - 84*s^5 + 70*s^6 - 20*s^7`.
- It starts from the measured joint state at the first control cycle after the
  command is received.
- It switches back to hold/raw mode after `tf` finishes.
- The Python wrapper returns after the command is accepted; callers that need a
  strict wait should sleep for `tf` plus margin or use `set_joint_waypoints()`.

实现逻辑：

- `set_joint()` 只设置一个目标点。
- 控制循环频率为 `400 Hz`。
- 轨迹使用七阶 smoothstep 多项式：
  `35*s^4 - 84*s^5 + 70*s^6 - 20*s^7`。
- 命令被控制循环接收后的第一个周期，会以当时实测关节状态作为起点。
- `tf` 结束后底层切回保持/raw 模式。
- Python 包装层在命令被接受后返回；如果需要严格等待，调用者应等待 `tf`
  加裕量，或优先使用 `set_joint_waypoints()`。

### `set_joint_raw(positions, velocities)`

Low-level joint command. Use it only for carefully managed servo loops.

低层关节命令。仅建议在上层自行严格管理伺服循环时使用。

```python
arm.set_joint_raw(q_target, dq_target)
```

Implementation:

- No high-level trajectory is planned for the user-provided sequence.
- In POS_VEL mode, the target position is sent with the configured speed limit.
- In MIT mode, the lower layer still applies a protective smoothing step using
  internal velocity and acceleration limits before sending the MIT command.
- If the caller sends commands slower than the internal `400 Hz` loop, the
  controller keeps using the latest target between updates; it does not invent
  a full replay trajectory from missing samples.

实现逻辑：

- 不会为用户提供的序列做高层轨迹规划。
- POS_VEL 模式下，底层下发目标位置和配置速度限制。
- MIT 模式下，底层仍会基于内部速度/加速度限制做保护性平滑，再发送 MIT 指令。
- 如果上层透传频率低于内部 `400 Hz` 控制循环，控制器会在两次上层更新之间持续使用最新目标；
  它不会自动根据缺失采样点重建完整复现轨迹。

## Cartesian Pose APIs

## 笛卡尔位姿接口

Cartesian poses use:

笛卡尔位姿格式为：

```python
[x, y, z, roll, pitch, yaw]
```

- `x, y, z`: meters.
- `roll, pitch, yaw`: radians.

- `x, y, z`：单位米。
- `roll, pitch, yaw`：单位弧度。

### `move_p(poses, time_sec=None, speed_percent=None, blend_radius_m=0.002, ...)`

Preferred Cartesian path API. Recommended for multi-point Cartesian trajectory
replay and VLA/cartesian policy deployment.

推荐的笛卡尔路径接口。适合多点笛卡尔轨迹复现以及 VLA/笛卡尔策略部署。

```python
poses = [
    [0.30, 0.00, 0.20, 0, 0, 0],
    [0.32, 0.02, 0.21, 0, 0, 0],
    [0.34, 0.02, 0.22, 0, 0, 0],
]

duration = arm.move_p(poses, time_sec=2.0, blend_radius_m=0.002)
duration = arm.move_p(poses, speed_percent=0.2, blend_radius_m=0.002)
duration = arm.move_p(poses)  # equivalent to speed_percent=0.1
```

```python
duration = arm.move_p(poses, time_sec=2.0, blend_radius_m=0.002)      # 时间模式
duration = arm.move_p(poses, speed_percent=0.2, blend_radius_m=0.002) # 速度模式
duration = arm.move_p(poses)                                         # 等价 speed_percent=0.1
```

Parameter rules are the same as `set_joint_waypoints()`:

- Pass only `time_sec` or only `speed_percent`.
- If neither is provided, the wrapper sends `speed_percent=0.1`.
- `time_sec` is the total time for the whole Cartesian path.
- `speed_percent` is normalized speed ratio.

参数规则与 `set_joint_waypoints()` 一致：

- 只能传 `time_sec` 或 `speed_percent` 其中一个。
- 如果两个都不传，包装层会按 `speed_percent=0.1` 下发。
- `time_sec` 是整条笛卡尔路径的总时长。
- `speed_percent` 是归一化速度比例。

Implementation:

- Cartesian poses are densified into joint waypoints through IK.
- Orientation interpolation uses quaternion slerp.
- `blend_radius_m` controls corner blending for the Cartesian path.
- The generated joint waypoints are executed by the same blocking 400Hz
  waypoint backend as `set_joint_waypoints()`.

实现逻辑：

- 笛卡尔位姿会通过 IK 转成稠密关节路点。
- 姿态插值使用四元数 slerp。
- `blend_radius_m` 控制笛卡尔路径拐角过渡。
- 生成的关节路点会交给与 `set_joint_waypoints()` 相同的 400Hz 阻塞式路点后端执行。

### `move_p_with_gripper(frames, time_sec=None, speed_percent=None, blend_radius_m=0.002, ...)`

VLA-friendly Cartesian frame API. Each frame contains arm pose and normalized
gripper position together. The arm trajectory is executed by `move_p()`, while
the gripper is driven by `setGripperPosition()` from a separate Python thread.

面向 VLA 的笛卡尔整帧接口。每一帧同时包含机械臂位姿和归一化夹爪开度。机械臂轨迹使用
`move_p()` 执行，夹爪由独立 Python 线程调用 `setGripperPosition()` 同步控制。

Accepted input formats:

支持的输入格式：

```python
# Nx7: [x, y, z, roll, pitch, yaw, gripper]
frames = [
    [0.30, 0.00, 0.20, 0, 0, 0, 1.0],
    [0.32, 0.02, 0.21, 0, 0, 0, 0.7],
    [0.34, 0.02, 0.22, 0, 0, 0, 0.2],
]
arm.move_p_with_gripper(frames, time_sec=5.0)
arm.move_p_with_gripper(frames, speed_percent=0.2)
arm.move_p_with_gripper(frames)  # equivalent to speed_percent=0.1

# Dataset-style dict:
batch = {
    "cmdpos": [[0.30, 0.00, 0.20], [0.32, 0.02, 0.21]],
    "cmdeulerrad": [[0, 0, 0], [0, 0, 0]],
    "cmdgripper": [1.0, 0.5],
}
arm.move_p_with_gripper(batch, time_sec=5.0)
```

Parameter rules are the same as `move_p()`:

- Pass only `time_sec` or only `speed_percent`.
- If neither is provided, the wrapper sends `speed_percent=0.1`.
- Use `time_sec` when the original frame timestamps must be replayed strictly.

参数规则与 `move_p()` 一致：

- 只能传 `time_sec` 或 `speed_percent` 其中一个。
- 如果两个都不传，包装层会按 `speed_percent=0.1` 下发。
- 需要严格复现原始帧时间戳时，优先使用 `time_sec`。

Gripper timing:

夹爪时序：

- The gripper values are not interpolated.
- In `time_sec` mode, frame `i` gripper value is sent at the same normalized time
  as frame `i` arm pose over the whole segment.
- In `speed_percent` mode, the arm backend chooses the segment duration from
  speed limits and does not expose per-frame timestamps to Python. The wrapper
  still sends the original gripper frames in the same order with an internal
  5ms minimum command interval; use `time_sec` for strict physical timestamp
  alignment.
- Gripper command timing is not a user parameter. The lower layer uses the
  gripper watchdog `command_period_ms` setting, default `5ms = 200Hz`; the Python
  wrapper does not command faster than that default.

- 夹爪值不会做插值。
- 在 `time_sec` 模式下，第 `i` 帧夹爪值会在整段轨迹中与第 `i` 帧机械臂位姿相同的归一化时刻下发。
- 在 `speed_percent` 模式下，机械臂底层会根据速度限制决定整段时长，且不会向 Python 暴露每帧时间戳。
  包装层仍按原始帧顺序、以内部 5ms 最小命令间隔逐帧下发夹爪；若需要严格物理时间戳对齐，请使用
  `time_sec`。
- 夹爪命令周期不是用户参数。底层使用 gripper watchdog 的 `command_period_ms` 配置，默认
  `5ms = 200Hz`；Python 包装层不会比该默认值更快地下发。

Blocking behavior:

阻塞机制：

- The call blocks until the arm `move_p()` segment finishes.
- The gripper thread starts immediately before the arm motion and stops when the
  arm segment returns.
- The final gripper value is sent once more after the arm segment finishes.

- 该调用会阻塞到机械臂 `move_p()` 段执行完成。
- 夹爪线程会在机械臂运动前立即启动，并在机械臂段返回后停止。
- 机械臂段结束后，会再次下发最后一帧夹爪值。

### `move_l(poses, time_sec=None, speed_percent=None, blend_radius_m=0.0, ...)`

Cartesian linear segment API. Use it when the tool center point must follow
linear segments more strictly. For general multi-point replay, prefer
`move_p()`.

笛卡尔直线段接口。适用于 TCP 需要更严格沿直线段运动的场景。一般多点轨迹复现优先使用
`move_p()`。

```python
duration = arm.move_l(poses, time_sec=2.0, blend_radius_m=0.0)
duration = arm.move_l(poses, speed_percent=0.2, blend_radius_m=0.0)
```

Implementation and blocking behavior are the same as `move_p()`, except the
Cartesian densification uses linear segments.

实现和阻塞行为与 `move_p()` 相同，区别是笛卡尔稠密化按直线段处理。

The older pose-waypoint API is not exposed in the public Python interface. Use
`move_p()` or `move_l()` instead.

旧的 pose-waypoint 接口不在公开 Python 接口中暴露。请使用 `move_p()` 或 `move_l()`。

## Gripper And Arm Timestamp Alignment

## 夹爪和机械臂时间戳对齐

For strict replay, send the arm path as one blocking waypoint/path call and
drive gripper targets from a separate timing thread using the same trajectory
timestamps.

严格复现时，建议把机械臂轨迹作为一个阻塞式路点/路径调用下发，同时用另一个计时线程按同一组时间戳下发夹爪目标。

```python
import threading
import time

def gripper_thread(arm, timestamps, gripper_positions, stop_event):
    t0 = time.monotonic()
    for t, g in zip(timestamps, gripper_positions):
        wait_s = t - (time.monotonic() - t0)
        if wait_s > 0 and stop_event.wait(wait_s):
            return
        if stop_event.is_set():
            return
        arm.setGripperPosition(float(g))

stop_event = threading.Event()
thread = threading.Thread(
    target=gripper_thread,
    args=(arm, timestamps, gripper_positions, stop_event),
)
thread.start()
try:
    arm.set_joint_waypoints(joint_waypoints, time_sec=timestamps[-1])
finally:
    stop_event.set()
    thread.join(timeout=1.0)
```

This pattern is used by the replay scripts: the arm call blocks until motion
ends, while the gripper thread follows recorded timestamps.

回放脚本采用的就是这种模式：机械臂调用阻塞到运动结束，同时夹爪线程按录制时间戳同步执行。

## MotionProgram

## 运动程序

`MotionProgram` combines multiple motion items and executes them through
`run_motion_program()`.

`MotionProgram` 用于组合多个运动项，并通过 `run_motion_program()` 执行。

```python
program = MotionProgram()
program.movej([[0, 0, 0, 0, 0, 0]], time_sec=1.0)
program.movej([[0, 0.2, -0.4, 0.5, 0, 0]], time_sec=1.0)
program.sleep(0.5)
program.movep(
    [
        [0.3, 0.0, 0.2, 0, 0, 0],
        [0.32, 0.0, 0.2, 0, 0, 0],
    ],
    time_sec=2.0,
    blend_radius_m=0.002,
)

duration = arm.run_motion_program(program)
```

Available items:

- `movej(waypoints, time_sec=None, speed_percent=None)`
- `movep(poses, time_sec=None, speed_percent=None, blend_radius_m=0.002)`
- `movel(poses, time_sec=None, speed_percent=None, blend_radius_m=0.0)`
- `sleep(sleep_sec)`

可用运动项：

- `movej(waypoints, time_sec=None, speed_percent=None)`
- `movep(poses, time_sec=None, speed_percent=None, blend_radius_m=0.002)`
- `movel(poses, time_sec=None, speed_percent=None, blend_radius_m=0.0)`
- `sleep(sleep_sec)`

Execution rules:

- `run_motion_program()` blocks until all motion and sleep items finish.
- Consecutive same-type motion items may be merged:
  consecutive `movej`, consecutive `movep`, or consecutive `movel`.
- Different motion types are not merged.
- `sleep()` is a hard breakpoint: pending motion is flushed and completed
  before sleep starts.
- In time mode, merged same-type motions accumulate `time_sec`.
- In speed mode, merged same-type motions must use the same `speed_percent`.
- For `movep` and `movel`, `blend_radius_m` must also match to merge.
- Returned `duration` is accumulated planned motion time and does not include
  sleep duration.

执行规则：

- `run_motion_program()` 会阻塞，直到所有运动项和 sleep 项完成。
- 连续同类型运动项可能被合并：连续 `movej`、连续 `movep` 或连续 `movel`。
- 不同运动类型不会合并。
- `sleep()` 是硬断点：底层会先完成并刷新待执行运动，再开始 sleep。
- 时间模式下，被合并的同类运动会累加 `time_sec`。
- 速度模式下，被合并的同类运动必须使用相同 `speed_percent`。
- 对 `movep` 和 `movel`，`blend_radius_m` 也必须相同才会合并。
- 返回的 `duration` 是累计规划运动时间，不包含 sleep 时间。

Gripper synchronization with `MotionProgram` uses the same separate-thread
pattern as direct waypoint replay. Include sleep time in your external gripper
timeline if the gripper action must align with wall time rather than only
planned arm motion time.

`MotionProgram` 下的夹爪同步同样使用独立线程方式。如果夹爪需要按真实墙钟时间对齐，而不是只对齐机械臂规划运动时间，
外部夹爪时间轴应把 `sleep()` 的时间也计入。

## Interrupt Handling

## 中断处理

Blocking waypoint and MotionProgram calls release the Python GIL but the worker
thread remains inside the C++ call until the motion finishes or the controller
is cleaned up/exits. For immediate safety, always rely on hardware E-stop.

阻塞式路点和 MotionProgram 调用会释放 Python GIL，但工作线程仍会停留在 C++ 调用内，直到运动结束或控制器 cleanup/退出。
需要立即安全停机时，必须依赖硬件急停。

Example script:

示例脚本：

```bash
python interface_py/interruptible_motion_example.py --execute
python interface_py/interruptible_motion_example.py --mode program --execute
```

The example runs the blocking arm call in a worker thread and handles Ctrl+C in
the main thread. On interrupt it calls `cleanup()`. This is useful for process
shutdown, but it is not a replacement for a hardware E-stop.

该示例把阻塞式机械臂调用放到工作线程，在主线程处理 Ctrl+C。中断时会调用 `cleanup()`。
这适合进程退出处理，但不能替代硬件急停。

## IK And End-Effector Helpers

## IK 和末端辅助接口

### `solve_ik(pos, quat, q_seed=None)`

```python
q, ok = arm.solve_ik(
    pos=[0.3, 0.0, 0.2],
    quat=[1.0, 0.0, 0.0, 0.0],
    q_seed=arm.get_joint_positions(),
)
```

Quaternion format is `[w, x, y, z]`.

四元数格式为 `[w, x, y, z]`。

If strict KDL IK fails and `ik_fallback.enabled` is true in
`src/config/robot_kinematics.yaml`, the lower layer may try a bounded
position-only fallback inside `ik_fallback.position_tolerance_m`. Accepted
fallbacks return `ok=True` and print a warning with the adjusted target and FK
error. Set `ik_fallback.enabled: false` to restore the old strict-only behavior.

如果严格 KDL IK 失败且 `src/config/robot_kinematics.yaml` 中
`ik_fallback.enabled` 为 true，底层会在 `ik_fallback.position_tolerance_m`
范围内尝试仅 XYZ 位置容差 fallback。fallback 成功时返回 `ok=True`，并打印调整后的目标点和
FK 误差。将 `ik_fallback.enabled` 设为 false 可恢复旧的严格 IK 行为。

### `get_ee_pose_euler()` / `get_ee_pose_quat()`

Read current end-effector pose.

读取当前末端位姿。

```python
pos, euler = arm.get_ee_pose_euler()
pos, quat = arm.get_ee_pose_quat()
```

The older direct end-effector set APIs remain available for compatibility, but
for replay and deployment use `move_p()`, `move_l()`, or
`set_joint_waypoints()`.

旧的直接设置末端接口仍为兼容保留，但轨迹复现和部署建议使用 `move_p()`、`move_l()` 或
`set_joint_waypoints()`。

## Units And Formats

## 单位和数据格式

| Data | Format | Unit |
| --- | --- | --- |
| Joint position | `[q1, q2, q3, q4, q5, q6]` | rad |
| Joint velocity | `[dq1, ..., dq6]` | rad/s |
| Cartesian pose | `[x, y, z, roll, pitch, yaw]` | m, rad |
| VLA Cartesian frame | `[x, y, z, roll, pitch, yaw, gripper]` | m, rad, ratio |
| Quaternion | `[w, x, y, z]` | unit quaternion |
| Gripper position | `0.0 ~ 1.0` | ratio |
| Gripper distance | `0.0 ~ 0.085` | m |
| `time_sec` / `tf` | scalar | s |

| 数据 | 格式 | 单位 |
| --- | --- | --- |
| 关节位置 | `[q1, q2, q3, q4, q5, q6]` | rad |
| 关节速度 | `[dq1, ..., dq6]` | rad/s |
| 笛卡尔位姿 | `[x, y, z, roll, pitch, yaw]` | m, rad |
| VLA 笛卡尔整帧 | `[x, y, z, roll, pitch, yaw, gripper]` | m, rad, 比例 |
| 四元数 | `[w, x, y, z]` | 单位四元数 |
| 夹爪开度 | `0.0 ~ 1.0` | 比例 |
| 夹爪距离 | `0.0 ~ 0.085` | m |
| `time_sec` / `tf` | 标量 | s |

## Safety Notes

## 安全说明

- Prefer `set_joint_waypoints()` for joint replay.
- Prefer `move_p()` for multi-point Cartesian replay.
- Prefer `move_p_with_gripper()` for VLA Cartesian pose plus gripper frame
  deployment.
- Use `time_sec` first for strict timestamped data replay.
- Use conservative `speed_percent`, for example `0.1 ~ 0.3`, for initial
  hardware tests.
- Verify CAN setup, emergency stop, workspace clearance, and initial robot pose
  before hardware execution.

- 关节轨迹复现优先使用 `set_joint_waypoints()`。
- 多点笛卡尔轨迹复现优先使用 `move_p()`。
- VLA 笛卡尔位姿加夹爪整帧部署优先使用 `move_p_with_gripper()`。
- 严格时间戳数据复现优先使用 `time_sec`。
- 初次真机测试建议使用保守 `speed_percent`，例如 `0.1 ~ 0.3`。
- 真机执行前必须确认 CAN、急停、工作空间和机器人初始位姿。

## LeRobot Data Collection And Teleoperation APIs

## LeRobot 数据采集和遥操作接口

Status: **not yet verified on the current hardware/software setup; still under
test**.

状态：**当前硬件/软件配置下尚未验证，仍在测试中**。

The scripts below are ROS 2 `JointState` bridges for LeRobot-style data
collection, teleoperation, and inference. They require ROS 2 Python packages
(`rclpy`, `sensor_msgs`) in addition to the base SDK dependencies. Treat this
section as API documentation for the current scripts, not as a validated
runtime procedure.

下面脚本是面向 LeRobot 风格数据采集、遥操作和推理的 ROS 2 `JointState` 桥接脚本。
除基础 SDK 依赖外，还需要 ROS 2 Python 包（`rclpy`、`sensor_msgs`）。
本节仅说明当前脚本接口，不代表已验证的运行流程。

Scripts:

脚本：

```bash
python interface_py/lerobot_single_arm_tele.py
python interface_py/lerobot_ow_right_arm.py
python interface_py/lerobot_ow_left_arm.py
python interface_py/lerobot_two_arm_inference.py
```

Important notes:

- Topic names, node names, shutdown handling, and command paths are still being
  verified.
- Some scripts use raw joint commands internally; operators must ensure safe
  workspace, low speed, emergency stop readiness, and correct CAN mapping.
- `lerobot_two_arm_inference.py` currently has robot command calls commented
  out; it publishes state and receives targets but does not drive the arms as
  written.

重要说明：

- topic 名称、node 名称、退出处理和命令链路仍在验证中。
- 部分脚本内部使用关节 raw 命令；操作者必须确保安全工作空间、低速、急停可用以及 CAN 映射正确。
- `lerobot_two_arm_inference.py` 当前机器人命令调用处于注释状态；按当前代码只发布状态并接收目标，不实际驱动机械臂。
