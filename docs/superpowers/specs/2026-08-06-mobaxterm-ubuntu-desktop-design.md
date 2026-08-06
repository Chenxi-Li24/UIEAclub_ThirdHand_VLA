# MobaXterm 远程控制 Ubuntu 桌面设计

## 目标

让 Windows 电脑通过 MobaXterm 查看并操作 Ubuntu `20.04` 当前已登录的 GNOME/Xorg 桌面，包括鼠标和键盘控制，同时不影响已有 SSH 会话。

## 当前环境

- Ubuntu 主机局域网地址为 `192.168.58.68`，Windows 客户端当前地址为 `192.168.58.74`。
- GNOME/Xorg 图形桌面正在运行，用户为 `nieqingcao`。
- OpenSSH 服务已启用并监听 `22/tcp`。
- Vino 已安装，但尚未运行，系统没有监听 VNC 端口。
- UFW 当前未启用。

## 方案选择

采用 Vino 共享现有桌面，并让 VNC 仅通过 SSH 隧道访问。

不直接向局域网开放 `5900/tcp`，避免未加密的 VNC 流量和弱 VNC 认证暴露在 Wi-Fi 网络中。不采用 XRDP，因为 XRDP 通常创建独立桌面会话，不能直接控制显示器上正在显示的同一桌面。X11 转发只适合启动单个 Linux 应用，也不满足完整桌面控制需求。

## Ubuntu 端配置

1. 在 `nieqingcao` 的图形会话中启用 Vino。
2. 允许远程端进行鼠标和键盘控制，不要求本机逐次弹窗确认。
3. 启用独立的随机 VNC 密码，不复用 Ubuntu 登录密码或 SSH 密码。
4. 将 Vino 绑定到回环接口，使 `5900/tcp` 不可从局域网直接访问。
5. 确保 Vino 随该用户的 GNOME 图形会话启动；不改变 SSH 服务和其他远程连接。

## Windows / MobaXterm 端配置

创建一个 MobaXterm VNC 会话，VNC 目标填写 Ubuntu 内部的 `127.0.0.1:5900`，并在该会话的 Network settings 中启用 SSH gateway，网关填写 `192.168.58.68:22` 和用户 `nieqingcao`。MobaXterm 会自动建立 SSH 隧道，不需要额外占用或管理 Windows 本地转发端口。连接 VNC 时使用独立 VNC 密码认证。

## 安全边界

- VNC 服务不得监听 Ubuntu 的 Wi-Fi 地址 `192.168.58.68`。
- VNC 密码不写入仓库、设计文档或 shell 历史；只在最终交付时提供给用户。
- SSH 仍是唯一暴露给局域网的远程管理端口。
- 不修改另一台电脑或已有 SSH 会话。

## 验证与回滚

验证项：Vino 进程正常、Ubuntu 仅在回环地址监听 VNC、SSH 仍可用、通过 SSH 隧道可完成 VNC 握手，并最终由用户在 MobaXterm 中验证桌面显示和键鼠操作。

若配置失败或用户不再需要远控，停止 Vino、关闭其自动启动并删除相应的用户级 Vino 设置；SSH 配置保持不变。
