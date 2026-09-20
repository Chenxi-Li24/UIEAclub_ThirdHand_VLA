# ThirdHand 一键启动说明

## 这个功能是什么

一键启动是开发者手动触发的一次性服务检查工具。它连接 Ubuntu 主机，保留已经正常
监听的服务，只按照配置顺序启动当前缺失的服务，显示每项结果后立即退出。

它不是后台守护、开机自启、自动重启、自动连接机械臂或一键停止工具。网页打开后，
开发者仍需根据需要手动点击“连接机械臂”。

## 文件和安装位置

| 项目 | 位置 |
|---|---|
| Ubuntu 当前仓库 | `/home/nieqingcao/ThirdHand/UIEAclub_ThirdHand_VLA` |
| 后端执行命令 | `./thirdhand ensure --profile manual-control` |
| Launcher 命令入口 | `apps/launcher/src/cli.js` |
| 检查与补齐实现 | `apps/launcher/src/service-supervisor.js` |
| 五项服务配置 | `configs/runtime/manual-control.json` |
| Windows 安装脚本 | `tools/launcher/windows/install-thirdhand-shortcut.ps1` |
| Ubuntu 安装脚本 | `tools/launcher/ubuntu/install-ubuntu-shortcut.sh` |
| Ubuntu 启动脚本 | `tools/launcher/ubuntu/start-thirdhand.sh` |
| 英文说明 | `docs/ONE_CLICK_START.md` |
| 中文说明 | `docs/ONE_CLICK_START_CN.md` |

Windows 安装完成后的实际位置：

- 桌面快捷方式：`Start ThirdHand.lnk`；
- 本地执行脚本：`%LOCALAPPDATA%\ThirdHand\Start-ThirdHand.cmd`；
- 最近一次运行日志：`%LOCALAPPDATA%\ThirdHand\last-run.log`。

当前 Windows 启动器版本为 `2026.09.18-3`。桌面快捷方式直接指向 CMD runner。
此前使用的 PowerShell runner `Start-ThirdHand.ps1` 已停用，不应继续使用。

当前 Ubuntu 主机安装完成后的实际位置：

- 桌面快捷方式：`/home/nieqingcao/桌面/Start ThirdHand.desktop`。

## 当前检查的服务

`manual-control` profile 按照以下顺序明确检查五个服务：

| 服务 | 地址 | 一键启动行为 |
|---|---|---|
| Robot Service | `127.0.0.1:3000` | 已监听就保留，否则启动；不会自动连接 CAN。 |
| Speech Service | `127.0.0.1:3004` | 已监听就保留，否则启动。 |
| Vision Service | `127.0.0.1:3100` | 已监听就保留，否则启动。 |
| Bottle-pick runtime | `127.0.0.1:8766` | 已监听就保留，否则启动。 |
| Web Gateway | `192.168.58.68:9983` | 已监听就保留，否则启动。 |

端口 `3200` 已停用，不属于当前一键启动范围。工具只检查端口和轻量服务身份，不会
修复模型、相机、依赖、CAN 状态或开发调试中的内部功能问题。

## 新 Windows 用户第一次使用

Windows 电脑必须能够访问 `192.168.58.68`，安装了 Windows OpenSSH，并使用这台
电脑自己的 SSH 密钥。快捷方式不会保存 Ubuntu 密码。

### 第一步：生成这台电脑自己的 SSH 密钥

如果这台电脑还没有密钥，在 PowerShell 执行：

```powershell
ssh-keygen -t ed25519
Get-Content "$env:USERPROFILE\.ssh\id_ed25519.pub"
```

只把显示出来的 `.pub` 公钥交给 Ubuntu 管理者。不要发送没有 `.pub` 后缀的
`id_ed25519`，它是私钥。管理员需要把公钥加入 Ubuntu 的 `nieqingcao` 账号。

### 第二步：确认 SSH 密钥可以使用

```powershell
ssh -o BatchMode=yes nieqingcao@192.168.58.68 true
```

命令应当直接结束，不应要求输入密码。如果失败，先完成 SSH 配置，再安装快捷方式。

### 第三步：下载安装脚本

```powershell
scp nieqingcao@192.168.58.68:/home/nieqingcao/ThirdHand/UIEAclub_ThirdHand_VLA/tools/launcher/windows/install-thirdhand-shortcut.ps1 "$env:USERPROFILE\Downloads\"

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$env:USERPROFILE\Downloads\install-thirdhand-shortcut.ps1"
```

运行完成后，Windows 桌面会出现 `Start ThirdHand`。

### 第四步：日常启动

双击桌面的 `Start ThirdHand`：

1. 快捷方式使用这台电脑自己的 SSH 密钥连接 Ubuntu；
2. 已经监听的服务保持不动，不会重启；
3. 缺失服务按照五项配置顺序启动；
4. 五项全部就绪时，窗口保留结果并等待开发者按 Enter，然后通过 Windows
   Explorer 打开 `http://192.168.58.68:9983/` 并关闭终端窗口；
5. 存在失败时，窗口保持打开并显示失败原因和日志路径；
6. 需要控制机械臂时，在 9983 网页中手动点击“连接机械臂”。

## 新 Ubuntu 用户第一次使用

进入当前仓库并安装桌面入口：

```bash
cd /home/nieqingcao/ThirdHand/UIEAclub_ThirdHand_VLA
tools/launcher/ubuntu/install-ubuntu-shortcut.sh
```

Ubuntu 桌面会出现 `Start ThirdHand`。双击后会打开终端，执行一次检查并显示结果；
Ubuntu 快捷方式不会自动打开浏览器，并会等待按 Enter 后再关闭。

也可以随时直接执行相同的后端命令：

```bash
cd /home/nieqingcao/ThirdHand/UIEAclub_ThirdHand_VLA
./thirdhand ensure --profile manual-control
```

## 输出结果说明

- `ready (kept)`：服务原本已经监听，本次没有重启。
- `ready (started)`：端口原本缺失，本次已经启动。
- `blocked_external`：端口有响应，但轻量服务身份与配置不符；不会自动杀进程。
- `failed (start_failed)`：本次启动的服务在超时前没有监听或已经退出。只清理本次
  新建的失败进程，其他成功服务继续运行。

服务日志位于：

```text
runtime/logs/<service>.stdout.log
runtime/logs/<service>.stderr.log
```

## Windows 快捷方式排障

如果 Windows 窗口在出现 Enter 提示前关闭：

1. 先不要删除快捷方式；
2. 查看 `%LOCALAPPDATA%\ThirdHand\last-run.log`，确认 CMD runner 是否启动以及执行到
   哪个阶段；
3. 确认窗口标题或第一行显示
   `ThirdHand One-Click Launcher 2026.09.18-3`；
4. 如果版本较旧，从 Ubuntu 当前仓库重新下载安装：

```powershell
scp nieqingcao@192.168.58.68:/home/nieqingcao/ThirdHand/UIEAclub_ThirdHand_VLA/tools/launcher/windows/install-thirdhand-shortcut.ps1 "$env:USERPROFILE\Downloads\"

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$env:USERPROFILE\Downloads\install-thirdhand-shortcut.ps1"
```

正常成功时，CMD 窗口会停在 `Press Enter to open ...`。按 Enter 后打开 9983 页面，
只关闭本次一键启动窗口；Ubuntu 上的五个服务会继续运行。

## 明确不会执行的操作

- 不重启已经监听且身份正确的服务；
- 不持续运行，不在 Ubuntu 开机时自动启动；
- 不自动恢复开发者后来手动停止的服务；
- 不自动连接机械臂、使能电机、回零或产生运动；
- 不停止或杀掉占用配置端口的未知进程；
- 不自动修复 ASR 模型、Vision 模型、相机、依赖或内部状态；
- 不提供一键停止全部服务。

以后增加后端服务时，开发者需要在 runtime profile 中明确填写启动命令、地址、超时
和轻量探针。Windows/Ubuntu 桌面入口不会扫描端口，也不会自动生成前端服务项目。
