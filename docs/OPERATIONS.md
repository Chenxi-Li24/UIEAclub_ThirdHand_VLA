# Unified Platform Operations

所有命令从仓库根目录执行：

```bash
./thirdhand doctor --profile PROFILE
./thirdhand start --profile PROFILE
./thirdhand ensure --profile PROFILE
./thirdhand status --profile PROFILE
./thirdhand stop --profile PROFILE
./thirdhand verify-assets
```

## Profiles

| Profile | 用途 | 访问硬件 | 服务 |
|---|---|---|---|
| `simulation` | 平台基础生命周期测试 | 否 | 五个 fake service |
| `manual-control-simulation` | 网页和 Robot Service 集成测试 | 否 | Robot 13000 + Web 9983 |
| `gripper-plan-simulation` | 不替换当前服务的浏览器授权链验收 | 否；Robot 强制模拟 | Robot 13000 + Orchestrator 13200 + Web 19983；只读复用当前 3004/3100 |
| `manual-control` | 人工监督的真机控制、语音和视觉 | Robot 仅在网页显式连接后访问 CAN；Vision 访问 XVisio | Robot 3000 + Speech 3004 + Vision 3100 + Bottle-pick 8766 + Web 9983 |
| `default` | 记录最终端口所有权 | 否，条目禁用 | 未选择正式验收 profile |

`start` 只启动 profile 中 `enabled: true` 的服务。服务必须写入
`runtime/run/<service>.ready` 后才算启动成功。重复执行不会创建第二套已归属服务。

`ensure` 是开发者手动触发的一次性“检查并补齐”：按 profile 顺序保留已监听的
预期服务，只启动端口缺失的服务，并在输出结果后退出。它不在后台运行、不做开机
自启、不自动恢复后来停止的服务，也不连接 Robot SDK。单项启动失败不会回滚其他
已成功服务；只清理由本次 `ensure` 创建但未能监听端口的进程。

## Process Ownership

状态记录位于 `runtime/run/state.json`。停止前同时核对：

- PID；
- Linux `/proc/<pid>/stat` 启动标记；
- 命令、参数和工作目录的 SHA-256。

任何一项不匹配都报告 `not_owned`，启动器不会向该 PID 发信号。

## Startup Order

服务按 profile 中的排列顺序启动；`shutdownOrder` 数值高的服务先停止。当前手动控制 profile：

1. Robot Service 启动，但不连接 SDK；
2. Speech Service 载入正式本地 ASR；
3. Vision Service 启动 XVisio 采集，识别模型独立加载；
4. Bottle-pick runtime 在 `127.0.0.1:8766` 启动；实机执行安全锁保持独立；
5. Web Gateway 最后监听 LAN 9983。

Robot Service 启动只产生空闲 Python 桥；浏览器连接 Web Gateway 也不会连接 SDK。只有浏览器显式发送 `{"cmd":"connect"}` 才允许 Robot Service 初始化硬件。

## Runtime Files

- `runtime/run/state.json`：服务所有权；
- `runtime/run/*.ready`：启动就绪标记；
- `runtime/run/robot-execution.token`：Launcher 管理的 32 字节私有执行令牌，权限 `0600`，完整停止后删除并在下次启动轮换；
- `runtime/logs/*.stdout.log`：标准输出；
- `runtime/logs/*.stderr.log`：错误输出。

这些文件不提交 Git。

## Failure Rules

- Robot Service 不可达：网页仍打开，但机械臂命令返回 `robot_service_unavailable`；
- Speech 不可达：`/voice` 关闭并显示本地语音服务不可用，不回退 Jetson 3001/3002；
- Vision 不可达：网页返回 `vision_upstream_unavailable`；模型失败时原始视频仍保持可用；
- CAN 无反馈或反馈过期：拒绝构造机械臂或拒绝运动；
- SDK 状态不足六关节、含非有限数或超过 500 ms：拒绝运动；
- 运动中的第二条命令：拒绝；
- 非显式 `zero` 预设的全零目标：拒绝；安全 `home` 是经过 commissioning 的非零姿态。
- Bottle-pick runtime 不可达、Robot 状态过期或目标证据无效：拒绝生成抓取任务；
- 重复确认、授权重放或执行原语重放：拒绝且不重试；
- 夹爪反馈超时或任一机械臂关节变化超过 0.5°：不得报告成功。

## Replacing External Services

当前 3000、3004、3100、8766 或 9983 由 Launcher 外部进程占用时，严格模式的
`thirdhand start` 会在启动任何子进程前失败。日常开发使用 `thirdhand ensure` 可保留
身份探测通过的已有服务，并只补齐缺失端口。切换整套进程所有权时仍必须人工完成：

1. 确认机械臂静止、工作区清空，物理急停或断电可触达；
2. 在当前页面断开 SDK，并确认 Robot health 为 `connected:false`；
3. 用 `ss -ltnp` 识别 3000、3004、3100、9983 的精确 PID；
4. 取得针对这些 PID 的明确停止授权后才停止；
5. 确认 3000、3004、3100、8766、9983 全部空闲；
6. 启动 `manual-control`，并核对 `runtime/run/state.json` 中所有 PID 均为 Launcher 所有。

Launcher 不会自动执行第 2 至第 4 步，也不会停止身份不匹配的进程。

## Emergency Behavior

页面“软件停止”请求 SDK 清理和电机失能。它依赖浏览器、网络、Node、Python、操作系统和 CAN，因此不是独立硬件急停。真机测试期间必须始终能触达物理急停或断电装置。

## Active Depth Alignment

网页 XVisio 区域的“开始深度对准”是唯一启动入口。先选择稳定目标，再单独点击开始；
目标选择、页面刷新、WebSocket 重连和服务启动都不会自动运动。Vision 返回
`robotControlEnabled:false` 是正常的权限归属标记，不是深度对准门控。

对准状态可从 `GET /api/active-depth/status` 和网页状态卡查看：`idle`、`observing`、
`moving`、`depth_acquired`、`failed`、`stopped`、`uncertain`。停止按钮调用受保护的
`POST /api/active-depth/stop`。若进入 `uncertain`，立即用物理急停或断电确认状态；
不得自动重试或反向运动。

运动顺序和硬限制：

- 优先 J4–J6；该层全部无有效改善候选后才允许 J1–J3，两个层级不能在同一步混动；
- J4–J6 单步不超过 2°、每关节累计不超过 10°；J1–J3 单步不超过 1°、累计不超过 5°；
- 相机中心单步位移不超过 5 mm、相对会话起点不超过 20 mm；
- 会话不超过 20 个完成步骤或 90 秒；必须取得三帧连续递增且有效的深度才算完成；
- 本流程不执行夹爪、下降、抓取或放置。

首次真机 commissioning 前，必须清空机械臂完整扫掠区域、保持物理急停可触达，
并把目标先放在深度 ROI 附近。分别观察第一个腕部步骤和第一个基座臂步骤是否与网页
预测方向一致。任何反向运动、目标切换、深度退化或停止状态不确定，都应终止测试。

## Git Policy

当前分支保持本地，不推送、不合并。原项目目录不被修改。Startouch SDK、模型权重、项目运行时和 URDF/STL 本体只保存在 Ubuntu 本地；Git 提交清单、哈希、协议、代码和准备脚本。
