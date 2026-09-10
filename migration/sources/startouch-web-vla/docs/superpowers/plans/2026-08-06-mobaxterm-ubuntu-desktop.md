# MobaXterm Ubuntu Desktop Access Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 Windows 上的 MobaXterm 通过 SSH 隧道安全地查看并控制 Ubuntu 当前 GNOME/Xorg 桌面。

**Architecture:** Ubuntu 使用已安装的 Vino 共享当前 X11 桌面，Vino 只绑定回环接口 `lo`。Windows 创建一个 VNC 会话，并使用该会话内置的 SSH gateway 自动通过 Ubuntu SSH 连接访问 `127.0.0.1:5900`。

**Tech Stack:** Ubuntu 20.04、GNOME/Xorg、Vino 3.22、OpenSSH、MobaXterm VNC 客户端

## Global Constraints

- 不修改或中断已有 SSH 会话和另一台电脑。
- VNC 不得监听 Ubuntu 的 Wi-Fi 地址 `192.168.58.68`。
- VNC 使用独立的随机 8 位密码，不复用 Ubuntu 或 SSH 密码。
- VNC 密码不得写入仓库或 shell 历史。
- Ubuntu 侧配置必须可回滚，且 Vino 应随 `nieqingcao` 的 GNOME 登录启动。

---

### Task 1: 配置当前 GNOME 用户的 Vino

**Files:**
- Modify: 用户 dconf 路径 `/org/gnome/desktop/remote-access/`
- Create: `/home/nieqingcao/.config/autostart/vino-server.desktop`

**Interfaces:**
- Consumes: 当前用户 D-Bus `unix:path=/run/user/1000/bus`、X11 显示 `:1`
- Produces: 仅回环可访问的 VNC 服务 `127.0.0.1:5900`

- [ ] **Step 1: 保存现有 Vino 设置以便回滚**

```bash
DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/1000/bus \
  dconf dump /org/gnome/desktop/remote-access/ \
  > /home/nieqingcao/.config/vino-settings-before-codex.ini
chmod 600 /home/nieqingcao/.config/vino-settings-before-codex.ini
```

备份文件允许为空：这表示实施前该路径没有用户级覆盖值，全部使用系统默认值。

- [ ] **Step 2: 生成密码并配置 Vino**

运行时用 `openssl rand` 生成 8 位字母数字密码，在同一非交互 shell 中编码后写入 dconf；只保留在进程内存和仅用户可读的临时交付文件，不把明文放入命令参数或 shell 历史。

```bash
umask 077
VNC_PASSWORD="$(openssl rand -base64 24 | tr -dc 'A-Za-z0-9' | head -c 8)"
printf '%s' "$VNC_PASSWORD" > /run/user/1000/codex-vino-password
VNC_PASSWORD_B64="$(printf '%s' "$VNC_PASSWORD" | base64 -w0)"
export DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/1000/bus
gsettings set org.gnome.Vino network-interface 'lo'
gsettings set org.gnome.Vino prompt-enabled false
gsettings set org.gnome.Vino view-only false
gsettings set org.gnome.Vino authentication-methods "['vnc']"
gsettings set org.gnome.Vino require-encryption false
gsettings set org.gnome.Vino use-upnp false
gsettings set org.gnome.Vino vnc-password "$VNC_PASSWORD_B64"
```

- [ ] **Step 3: 创建 GNOME 自启动项**

创建 `/home/nieqingcao/.config/autostart/vino-server.desktop`：

```ini
[Desktop Entry]
Name=Desktop Sharing
Comment=GNOME Desktop Sharing Server over SSH tunnel
Exec=/usr/lib/vino/vino-server --sm-disable
Icon=preferences-desktop-remote-desktop
NoDisplay=true
Terminal=false
Type=Application
X-GNOME-Autostart-Phase=Applications
X-GNOME-AutoRestart=true
X-GNOME-UsesNotifications=true
X-Ubuntu-Gettext-Domain=vino
```

- [ ] **Step 4: 启动当前会话的 Vino**

```bash
systemctl --user start vino-server.service
systemctl --user is-active vino-server.service
```

预期：第二条命令输出 `active`。

- [ ] **Step 5: 验证监听范围和 RFB 握手**

```bash
ss -lntp | grep -E '127\.0\.0\.1:5900|\[::1\]:5900'
timeout 3 bash -c 'exec 3<>/dev/tcp/127.0.0.1/5900; head -c 12 <&3'
```

预期：VNC 只监听回环地址，握手输出以 `RFB ` 开头；`192.168.58.68:5900` 不得出现。

### Task 2: 配置带 SSH gateway 的 MobaXterm VNC 会话

**Files:**
- None（Windows MobaXterm 会话配置）

**Interfaces:**
- Consumes: Ubuntu SSH `192.168.58.68:22`、Ubuntu VNC `127.0.0.1:5900`
- Produces: 一个经 SSH 加密的 MobaXterm VNC 桌面窗口

- [ ] **Step 1: 在 MobaXterm 创建 VNC 会话**

打开 `Session` → `VNC`，在 Basic VNC settings 中填写：

```text
Remote hostname or IP address: 127.0.0.1
Port: 5900
View only: off
```

进入该 VNC 会话的 `Network settings`，勾选 `Connect through SSH gateway (jump host)`，填写：

```text
Gateway SSH server: 192.168.58.68
Port: 22
User: nieqingcao
```

若 SSH 使用私钥，选择现有 `LAN-Ubuntu-SSH` 会话使用的同一私钥。保存后连接，先完成 SSH 认证，再输入 Task 1 生成的独立 VNC 密码。

- [ ] **Step 2: 验收桌面控制**

确认窗口显示 Ubuntu 当前桌面，鼠标移动和键盘输入可作用于该桌面，并确认已有 SSH 终端仍可正常执行 `hostname`。

### Task 3: 最终安全检查与交付

**Files:**
- Verify: `/home/nieqingcao/.config/autostart/vino-server.desktop`
- Verify: `/home/nieqingcao/.config/vino-settings-before-codex.ini`

**Interfaces:**
- Consumes: Task 1 的 Vino 服务和 Task 2 的客户端配置
- Produces: 可复核的安全状态与回滚入口

- [ ] **Step 1: 检查没有向局域网开放 VNC**

```bash
ss -lntp | grep ':5900'
sudo -n ufw status verbose
systemctl is-active ssh
```

预期：`5900` 仅出现在 `127.0.0.1`/`::1`，UFW 仍保持原状态，SSH 输出 `active`。

- [ ] **Step 2: 检查自启动文件和设置**

```bash
test -f /home/nieqingcao/.config/autostart/vino-server.desktop
DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/1000/bus \
  gsettings get org.gnome.Vino network-interface
DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/1000/bus \
  gsettings get org.gnome.Vino authentication-methods
```

预期：文件存在，设置分别为 `'lo'` 和 `['vnc']`。

- [ ] **Step 3: 交付连接参数并删除临时密码文件**

将 `/run/user/1000/codex-vino-password` 的值仅在最终回复中提供给用户，然后删除该临时文件：

```bash
shred -u /run/user/1000/codex-vino-password
```

回滚时执行：

```bash
systemctl --user stop vino-server.service
rm /home/nieqingcao/.config/autostart/vino-server.desktop
DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/1000/bus \
  dconf reset -f /org/gnome/desktop/remote-access/
DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/1000/bus \
  dconf load /org/gnome/desktop/remote-access/ \
  < /home/nieqingcao/.config/vino-settings-before-codex.ini
```
