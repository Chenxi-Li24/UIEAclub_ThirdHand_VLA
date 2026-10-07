# StarTouch SDK Installation and Runtime Guide

This document describes how to install the StarTouch/FastTouch SDK, build the
Python extension, and run the verified SDK examples.

本文档说明如何安装 StarTouch/FastTouch SDK、构建 Python 扩展，并运行已验证的 SDK 示例。

Current SDK version: `0.1.7`.

Version note: `2026-06-05`, author `Charlie`.

当前 SDK 版本：`0.1.7`。

版本说明：`2026-06-05`，作者 `Charlie`。

Important release behavior changes are recorded in `CHANGELOG.md`.

重要版本行为变化记录在 `CHANGELOG.md`。

After installation, query the version with:

安装后可通过以下方式查询版本：

```bash
python -c "import startouch; from startouchclass import __version__; print(startouch.__version__, __version__)"
```

## Supported System

The current CMake configuration selects a bundled `libstartouch.so` according
to the Linux distribution version. Supported Ubuntu/Debian versions are:

当前 CMake 配置会根据 Linux 发行版版本选择随包提供的 `libstartouch.so`。
支持的 Ubuntu/Debian 版本包括：

- Ubuntu 20.04
- Ubuntu 22.04
- Ubuntu 24.04 or newer compatible versions

The SDK requires Python 3.8 or newer. Python 3.10 is recommended and is the
environment used by the current project scripts.

SDK 要求 Python 3.8 或更高版本。推荐 Python 3.10，当前项目脚本也以该环境为主。

## System Dependencies

Install build tools and C++ dependencies:

安装构建工具和 C++ 依赖：

```bash
sudo apt-get update
sudo apt-get install -y build-essential cmake pkg-config libeigen3-dev libyaml-cpp-dev liborocos-kdl-dev libtinyxml2-dev pybind11-dev
```

Notes:

- `cmake`, `build-essential`, `libeigen3-dev`, and `pybind11-dev` are required
  by the local CMake/pybind11 build.
- `pkg-config`, `libyaml-cpp-dev`, and `libtinyxml2-dev` are required by the
  bundled `libstartouch.so` build/runtime dependency chain. `tinyxml2` is used
  by the C++ kinematics/URDF parser.
- `liborocos-kdl-dev` is needed by the kinematics headers used in the SDK
  source tree.
- `Threads` is provided by the system toolchain and is resolved by CMake.

If you use CAN devices, configure and bring up the CAN interface before running
hardware scripts:

如果使用 CAN 设备，在运行硬件脚本前需要配置并启动 CAN 口：

```bash
sudo ip link set can0 up type can bitrate 1000000
sudo ip link set can1 up type can bitrate 1000000
```

Adjust `can0`/`can1` and bitrate according to your hardware setup.

请根据实际硬件调整 `can0`/`can1` 和 bitrate。

## Python Environment

Create and activate a conda environment:

创建并激活 conda 环境：

```bash
conda create -n LumosTouch python=3.10 -y
conda activate LumosTouch
python -m pip install --upgrade pip setuptools wheel
```

## Install Python Dependencies and SDK

Run the following commands in the SDK root:

在 SDK 根目录执行以下命令：

```bash
cd /home/lumos/code/FastTouchV2/fnl/fnl/startouch_sdk
python -m pip install -r requirements.txt
python -m pip install .
```

For development, use editable install:

开发调试时可使用 editable 安装：

```bash
python -m pip install -e .
```

The Python dependencies are declared in both `requirements.txt` and
`pyproject.toml`. They include:

Python 依赖同时写在 `requirements.txt` 和 `pyproject.toml` 中，包括：

- `scikit-build-core`
- `pybind11`
- `packaging>=24`
- `typer`
- `numpy`
- `scipy`
- `PyYAML`
- `python-can>=4.3.1`
- `tqdm`
- `matplotlib`
- `opencv-python`
- `pillow`
- `h5py`
- `jinja2`
- `typeguard`

`jinja2` and `typeguard` are included because ROS-related Python packages such
as `generate-parameter-library-py` require them in common LumosTouch
environments. Keeping them in the base SDK dependency list makes `pip check`
clean after following this install guide.

`jinja2` 和 `typeguard` 已纳入基础依赖，因为常见 LumosTouch 环境中的 ROS 相关 Python 包
（例如 `generate-parameter-library-py`）会依赖它们。这样按本安装说明执行后，`pip check`
应保持无缺失依赖。

## Optional ROS 2 Dependencies

The LeRobot data collection and teleoperation scripts use ROS 2 Python APIs:

LeRobot 数据采集和遥操作脚本使用 ROS 2 Python API：

- `rclpy`
- `sensor_msgs`

These are not pip dependencies. Install/source a ROS 2 environment compatible
with your system, then verify imports:

这些不是 pip 依赖。请安装或 source 与系统匹配的 ROS 2 环境，然后验证导入：

```bash
python -c "import rclpy; from sensor_msgs.msg import JointState"
```

The LeRobot scripts are documented in `README_API.md` as currently unverified
interfaces.

LeRobot 脚本在 `README_API.md` 中标注为当前尚未验证的接口。

## Optional OpenPI / SAM3 Dependencies

The online policy rollout scripts such as
`interface_py/pi0_rollout_single_startouch_lxh.py` and
`interface_py/pi0_rollout_single_startouch_lxh_waypoints.py` import
`openpi_client` and SAM3 modules. These dependencies are outside the base SDK
requirements and must be installed/provided by the OpenPI/SAM3 runtime
environment before using those scripts.

在线策略 rollout 脚本，例如 `interface_py/pi0_rollout_single_startouch_lxh.py`
和 `interface_py/pi0_rollout_single_startouch_lxh_waypoints.py`，会导入
`openpi_client` 和 SAM3 模块。这些依赖不属于基础 SDK 依赖，使用这些脚本前需要由
OpenPI/SAM3 运行环境单独提供。

## Manual CMake Build

Normally `python -m pip install .` builds through `scikit-build-core`. If you
need a manual CMake build:

通常 `python -m pip install .` 会通过 `scikit-build-core` 构建。如需手动 CMake 构建：

```bash
cd /home/lumos/code/FastTouchV2/fnl/fnl/startouch_sdk
mkdir -p build
cd build
cmake ..
make -j
cd ..
```

The CMake build writes the `startouch` Python extension to `interface_py/` and
copies the OS-version-specific `libstartouch.so` into `src/libstartouch.so`.

CMake 构建会将 `startouch` Python 扩展写入 `interface_py/`，并把匹配系统版本的
`libstartouch.so` 复制到 `src/libstartouch.so`。

## Basic Verification

Passive joint reading, without active command:

被动读取关节，不主动下发运动命令：

```bash
cd /home/lumos/code/FastTouchV2/fnl/fnl/startouch_sdk
python interface_py/read_joints_passive.py
```

Hardware connectivity test:

硬件连接测试：

```bash
python interface_py/test_hardware.py
```

MoveJ / MotionProgram test:

MoveJ / MotionProgram 测试：

```bash
python interface_py/test_motion_program_movej.py
```

Add `--execute` to run motion on hardware after CAN is configured.

CAN 配置完成后，加 `--execute` 才会在真机上执行运动。

MoveP Cartesian test:

MoveP 笛卡尔测试：

```bash
python interface_py/test_movep_cartesian.py
```

Add `--execute` to run motion on hardware after CAN is configured.

CAN 配置完成后，加 `--execute` 才会在真机上执行运动。

Interactive IK / dual-arm example:

交互式 IK / 双臂示例：

```bash
python interface_py/ik.py
```

## Creating Arm Instances

After creating a `SingleArm`, keep a short delay before issuing motion commands
so the controller can initialize and move/settle safely.

创建 `SingleArm` 后，建议短暂等待再下发运动命令，让控制器完成初始化并稳定。

Single arm:

```python
import time
from startouchclass import SingleArm

arm_controller = SingleArm(can_interface_="can0", enable_fd_=False)
time.sleep(2)
```

Dual arm:

```python
import time
from startouchclass import SingleArm

arm_right = SingleArm(can_interface_="can0", enable_fd_=False)
arm_left = SingleArm(can_interface_="can1", enable_fd_=False)
time.sleep(2)
```

Current scripts use `enable_fd_=False`; CAN FD is not part of the validated
runtime path.

当前脚本使用 `enable_fd_=False`；CAN FD 不属于当前已验证运行路径。

## Replay Configuration

The current MoveP replay scripts read this config file:

当前 MoveP 回放脚本读取以下配置文件：

```text
interface_py/replay_refresh_config.yaml
```

They do not read `config.yaml` from the current working directory.

它们不会读取当前工作目录下的 `config.yaml`。

Important fields:

重要字段：

```yaml
DATA_ROOT: "/home/lumos/code/FastTouchV2/fnl/fnl/fastumi/DATA"
dual_multi_session_dir: "/home/lumos/code/FastTouchV2/fnl/fnl/fastumi/DATA/multi_session_20260430"
speed_rate: 1
initial_joints: [0, 0.1, -0.1, 0.1, 0, 0]

StarTouch:
    enable: true

SingleArm:
    single_port: "can0"
    T_base2local: ...

DualArm:
    left_can_port: "can0"
    right_can_port: "can1"
    left_T_base2local: ...
    right_T_base2local: ...
```

`T_base2local` is a standard homogeneous transform:

`T_base2local` 是标准齐次变换矩阵：

```text
T_base_pose = T_base2local @ T_recorded_pose
```

The replay scripts align gripper data by pose timestamps and send gripper
targets from a separate sync thread while MoveP is executing.

回放脚本会按位姿时间戳对齐夹爪数据，并在 MoveP 执行期间通过独立同步线程下发夹爪目标。

## Single-Arm Replay

```bash
cd /home/lumos/code/FastTouchV2/fnl/fnl/startouch_sdk
python interface_py/replay_movep.py
```

The script asks you to select a `multi_session*` directory and then a
`session_*` directory. It reads:

脚本会要求选择一个 `multi_session*` 目录，然后选择 `session_*` 目录。它读取：

```text
session_*/Merged_Trajectory/merged_trajectory.txt
session_*/Clamp_Data/clamp_data_tum.txt
```

## Dual-Arm Replay

```bash
cd /home/lumos/code/FastTouchV2/fnl/fnl/startouch_sdk
python interface_py/replay_movep_dual.py
```

The script reads sessions under `dual_multi_session_dir` and matches:

脚本会读取 `dual_multi_session_dir` 下的 session，并匹配：

```text
left_hand_*/Merged_Trajectory/merged_trajectory.txt
left_hand_*/Clamp_Data/clamp_data_tum.txt
right_hand_*/Merged_Trajectory/merged_trajectory.txt
right_hand_*/Clamp_Data/clamp_data_tum.txt
```

Dual-arm replay runs both arms concurrently. If either arm fails, the script
waits for worker threads to exit before cleaning up controller resources.

双臂回放会并发运行两只机械臂。如果任一机械臂失败，脚本会等待工作线程退出后再清理控制器资源。

## Common Issues

### `ModuleNotFoundError`

Confirm that the conda environment is active and the SDK is installed:

确认 conda 环境已激活，并且 SDK 已安装：

```bash
conda activate LumosTouch
cd /home/lumos/code/FastTouchV2/fnl/fnl/startouch_sdk
python -m pip install -r requirements.txt
python -m pip install .
```

### Missing ROS 2 Modules

If `rclpy` or `sensor_msgs` cannot be imported, source your ROS 2 environment
or install the matching ROS 2 packages for your Ubuntu version.

如果无法导入 `rclpy` 或 `sensor_msgs`，请 source ROS 2 环境，或安装与 Ubuntu 版本匹配的
ROS 2 包。

### Replay Config Not Found

Current replay scripts read:

当前回放脚本读取：

```text
interface_py/replay_refresh_config.yaml
```

They do not use the legacy `Replay_refresh/config.yaml`.

它们不使用旧的 `Replay_refresh/config.yaml`。

## IK Fallback Configuration

`src/config/robot_kinematics.yaml` includes `ik_fallback`. When enabled, strict
KDL IK failure can be recovered by a bounded XYZ-only fallback:

```yaml
ik_fallback:
  enabled: true
  position_tolerance_m: 0.005
  max_candidates: 32
  max_time_ms: 3.0
```

Set `enabled: false` to restore the old behavior where strict IK failure returns
`ok=False` immediately.

`src/config/robot_kinematics.yaml` 中包含 `ik_fallback`。启用后，严格 KDL IK
失败时会尝试有界 XYZ 容差 fallback。若需要完全恢复旧行为，将 `enabled` 设为 false。

### IK Residual Too Large

This usually means the target pose is unreachable or the coordinate transform is
incorrect. Check:

这通常表示目标位姿不可达，或坐标变换不正确。请检查：

- `SingleArm.T_base2local`
- `DualArm.left_T_base2local`
- `DualArm.right_T_base2local`
- whether the recorded coordinate frame and robot TCP frame require an
  additional fixed transform

### Requested `time_sec` Too Short

For time-mode waypoint trajectories, the requested duration must be long enough
for the number of trajectory samples and control frequency. If this still
occurs in replay, check the trajectory point count and the internal 400 Hz path
sampling constraint.

对于时间模式的路点轨迹，请求时长必须足够容纳轨迹采样点数量和控制频率。如果回放中仍出现该问题，
请检查轨迹点数量和内部 400 Hz 路径采样约束。
