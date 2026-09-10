# Unified Platform Operations

所有命令从仓库根目录执行：

```bash
./thirdhand doctor --profile PROFILE
./thirdhand start --profile PROFILE
./thirdhand status --profile PROFILE
./thirdhand stop --profile PROFILE
./thirdhand verify-assets
```

## Profiles

| Profile | 用途 | 访问硬件 | 服务 |
|---|---|---|---|
| `simulation` | 平台基础生命周期测试 | 否 | 五个 fake service |
| `manual-control-simulation` | 网页和 Robot Service 集成测试 | 否 | Robot 13000 + Web 9983 |
| `manual-control` | 人工监督的 Startouch 真机控制 | 仅显式网页连接后 | Robot 3000 + Web 9983 |
| `default` | 记录最终端口所有权 | 否，条目禁用 | 未选择正式验收 profile |

`start` 只启动 profile 中 `enabled: true` 的服务。服务必须写入
`runtime/run/<service>.ready` 后才算启动成功。重复执行不会创建第二套已归属服务。

## Process Ownership

状态记录位于 `runtime/run/state.json`。停止前同时核对：

- PID；
- Linux `/proc/<pid>/stat` 启动标记；
- 命令、参数和工作目录的 SHA-256。

任何一项不匹配都报告 `not_owned`，启动器不会向该 PID 发信号。

## Startup Order

`shutdownOrder` 数值高的服务先启动、先停止。当前手动控制 profile：

1. Robot Service，顺序 100；
2. Web Gateway，顺序 10。

Robot Service 启动只产生空闲 Python 桥；浏览器连接 Web Gateway 也不会连接 SDK。只有浏览器显式发送 `{"cmd":"connect"}` 才允许 Robot Service 初始化硬件。

## Runtime Files

- `runtime/run/state.json`：服务所有权；
- `runtime/run/*.ready`：启动就绪标记；
- `runtime/logs/*.stdout.log`：标准输出；
- `runtime/logs/*.stderr.log`：错误输出。

这些文件不提交 Git。

## Failure Rules

- Robot Service 不可达：网页仍打开，但机械臂命令返回 `robot_service_unavailable`；
- Vision/Speech 尚未迁移：相关 HTTP 或 WebSocket 命令返回 `service_unavailable`；
- CAN 无反馈或反馈过期：拒绝构造机械臂或拒绝运动；
- SDK 状态不足六关节、含非有限数或超过 500 ms：拒绝运动；
- 运动中的第二条命令：拒绝；
- 非显式 home 的全零目标：拒绝。

## Emergency Behavior

页面“软件停止”请求 SDK 清理和电机失能。它依赖浏览器、网络、Node、Python、操作系统和 CAN，因此不是独立硬件急停。真机测试期间必须始终能触达物理急停或断电装置。

## Git Policy

当前分支保持本地，不推送、不合并。原项目目录不被修改。Startouch SDK、模型权重、项目运行时和 URDF/STL 本体只保存在 Ubuntu 本地；Git 提交清单、哈希、协议、代码和准备脚本。
