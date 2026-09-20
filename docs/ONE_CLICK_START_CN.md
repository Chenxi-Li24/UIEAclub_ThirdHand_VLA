# ThirdHand 一键启动说明

## 功能

一键启动是开发者手动触发的一次性 CAN 与服务检查工具。它连接 Ubuntu 主机，先准备
`can0`，再保留已经正常运行的服务，只按配置顺序启动缺失的服务，显示结果后退出。

它不是后台守护程序，不会随 Ubuntu 开机自动运行，也不会自动连接机械臂。进入 9983
网页后，是否连接或断开 Startouch SDK 仍由用户手动决定。

## 位置

| 项目 | 位置 |
|---|---|
| Ubuntu 仓库 | `/home/nieqingcao/ThirdHand/UIEAclub_ThirdHand_VLA` |
| 一键启动命令 | `./thirdhand ensure --profile manual-control` |
| Launcher 入口 | `apps/launcher/src/cli.js` |
| 服务检查实现 | `apps/launcher/src/service-supervisor.js` |
| CAN 检查与配置 | `apps/launcher/src/can-interface.js` |
| 两级恢复编排 | `apps/launcher/src/runtime-ensure.js` |
| 运行配置 | `configs/runtime/manual-control.json` |
| Windows 安装脚本 | `tools/launcher/windows/install-thirdhand-shortcut.ps1` |
| Ubuntu 安装脚本 | `tools/launcher/ubuntu/install-ubuntu-shortcut.sh` |
| Ubuntu 启动脚本 | `tools/launcher/ubuntu/start-thirdhand.sh` |

Windows 安装后的文件：

- 桌面快捷方式：`Start ThirdHand.lnk`
- 本地执行脚本：`%LOCALAPPDATA%\ThirdHand\Start-ThirdHand.cmd`
- 最近一次日志：`%LOCALAPPDATA%\ThirdHand\last-run.log`

Ubuntu 桌面快捷方式：`/home/nieqingcao/桌面/Start ThirdHand.desktop`。

## CAN 检查与两级恢复

检查五项服务前，`manual-control` 会确认 `can0` 满足：

- 接口为 `UP`
- 波特率为 `1000000`
- 自动恢复参数为 `restart-ms 100`

一级恢复是正常路径：

- `can0` 配置正确时显示 `kept`，不重置 CAN，也不重启服务。
- 新启动时如果 CAN 为 DOWN 或配置错误，执行：
  `down -> type can bitrate 1000000 restart-ms 100 -> up`。

二级恢复只用于类似 2026-09-20 的极端情况：

- CAN 异常时 Robot Service 已经运行；或者
- 已有 CAN 计数显示 `TX>0、RX=0`，说明之前出现单向通信或旧状态。

二级恢复按当天 teammate 验证成功的顺序执行：

```bash
./thirdhand stop --profile manual-control
sudo ip link set can0 down
sudo ip link set can0 type can bitrate 1000000 restart-ms 100
sudo ip link set can0 up
./thirdhand start --profile manual-control
```

如果 PCAN 不存在、sudo 权限失效或恢复后的接口验证失败，终端会显示具体原因；其他
五项服务仍会继续检查。

无论一级还是二级恢复，一键启动都不会发送 `{ "cmd": "connect" }`，不会自动加载
Startouch SDK，不会使能电机，也不会执行 Home、Zero、关节或夹爪动作。

## 当前五项服务

| 服务 | 地址 | 一键启动行为 |
|---|---|---|
| Robot Service | `127.0.0.1:3000` | 正常时保留，否则启动；只有二级 CAN 恢复才重启 profile。 |
| Speech Service | `127.0.0.1:3004` | 正常时保留，否则启动。 |
| Vision Service | `127.0.0.1:3100` | 正常时保留，否则启动。 |
| Bottle-pick runtime | `127.0.0.1:8766` | 正常时保留，否则启动。 |
| Web Gateway | `192.168.58.68:9983` | 正常时保留，否则启动。 |

端口 `3200` 已停用，不属于当前流程。工具不会修复 ASR/Vision 模型、相机、依赖或
应用内部的调试问题。

## Windows 新用户使用

Windows 电脑必须能够访问 `192.168.58.68`，并安装 Windows OpenSSH Client。

### 1. 创建本机 SSH 密钥

```powershell
ssh-keygen -t ed25519
Get-Content "$env:USERPROFILE\.ssh\id_ed25519.pub"
```

只把 `.pub` 公钥交给 Ubuntu 管理员，不要发送私钥 `id_ed25519`。

### 2. 验证免密登录

```powershell
ssh -o BatchMode=yes nieqingcao@192.168.58.68 true
```

该命令应直接结束，不应要求输入密码。

### 3. 下载并安装快捷方式

```powershell
scp nieqingcao@192.168.58.68:/home/nieqingcao/ThirdHand/UIEAclub_ThirdHand_VLA/tools/launcher/windows/install-thirdhand-shortcut.ps1 "$env:USERPROFILE\Downloads\"

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$env:USERPROFILE\Downloads\install-thirdhand-shortcut.ps1"
```

### 4. 日常使用

双击桌面的 `Start ThirdHand`：

1. 连接 Ubuntu；
2. 检查并按需恢复 `can0`；
3. 保留正常服务并启动缺失服务；
4. 成功后按 Enter 打开 `http://192.168.58.68:9983/`；
5. 在网页中手动点击“连接机械臂”或“断开”。

按 Enter 后只会关闭本地一键启动窗口，Ubuntu 上的 CAN 和服务继续运行。

## Ubuntu 新用户使用

安装桌面快捷方式：

```bash
cd /home/nieqingcao/ThirdHand/UIEAclub_ThirdHand_VLA
tools/launcher/ubuntu/install-ubuntu-shortcut.sh
```

Ubuntu 快捷方式会打开终端、运行一次检查并等待 Enter，不会自动打开浏览器。也可以
直接运行：

```bash
cd /home/nieqingcao/ThirdHand/UIEAclub_ThirdHand_VLA
./thirdhand ensure --profile manual-control
```

## 结果说明

- `can: ready (kept)`：CAN 已符合配置，没有重置 CAN 或服务。
- `can: ready (reconfigured)`：一级恢复已配置并启动 CAN。
- `can: ready (full_recovery)`：已执行二级恢复，重建 CAN 并恢复 profile。
- `can: failed`：CAN 未能恢复；查看后面的 `reason` 和 `detail`。
- `ready (kept)`：服务原本已正常运行，没有被重启。
- `ready (started)`：服务原本缺失，本次已启动。
- `blocked_external`：端口被身份不匹配的进程占用，不会自动杀进程。
- `failed (start_failed)`：新启动的服务未在超时前监听或已经退出。

服务日志：

```text
runtime/logs/<service>.stdout.log
runtime/logs/<service>.stderr.log
```

## 明确不会执行的操作

- 不会持续监听，也不会设置 Ubuntu 开机自启动。
- 不会在 CAN 正常时重启已有服务。
- 不会自动恢复开发者之后手动停止的服务，除非再次点击一键启动。
- 不会自动连接机械臂、使能电机、回零或移动机械臂。
- 不会杀死占用端口的未知进程。
- 不会自动修复相机、模型、依赖或应用内部状态。
- 不提供一键停止全部服务的按钮。

以后增加后端服务时，需要由开发者明确加入 runtime profile；前端不会扫描或自动增加
未知端口。
