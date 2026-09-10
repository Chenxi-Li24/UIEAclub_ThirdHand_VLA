# Startouch 方案 A 安全加固设计

**状态：** 用户已于 2026-08-24 批准实施方案 A。

**范围：** 仅修改 `PinZiZhuaQuSkill`，只做离线开发和验证；不连接机械臂、不打开 `execution_enabled`。

## 目标

在保持“输入瓶子编号”的现有交互和法兰位姿协议不变的前提下，把 Reuse 已经离线验证的 Startouch 安全边界作为项目内独立模块引入。实机入口必须在导入厂商 SDK 前证明运行时资产、安全配置、许可记录和二进制来源身份；任一不满足即闭锁。

## 安全不变量

- 项目内运行时只包含清单列出的 SDK 资产，每个文件都校验 SHA-256，多余/影子模块一律拒绝。
- 安全剖面启用加速度/加加速度限制、奇异保护、轨迹安全、运行时关节安全、自碰撞与夹爪看门狗；厂商 3° (`0.05236 rad`) 关节停机余量不得缩小。
- 启动姿态若已进入任一关节的 3° 余量，直接拒绝。现有 HOME 仅作待监督验证候选，不猜测新 HOME。
- CAN 启动证据必须是 SocketCAN 被动收到的 `0x11..0x17` 全部反馈 ID。`MSG_DONTROUTE` 本机回环、RTR、ERR 和无关帧都不能充当证据。
- SDK `cleanup()` 返回只记为 `cleanup_acknowledged=true` 和 `cleanup_confirmation_mode=vendor_cleanup_returned`；始终记为 `depower_independently_confirmed=false`，不宣称掉电或急停。
- Node 与 Python 握手同时绑定项目内源码内容 ID、运行参数 ID、安全剖面 ID、安全配置哈希和运行时清单 ID。
- 批准设计时，本机绑定二进制的可复现构建证据为 `false`。2026-08-24 后续实施已用两份独立干净源码导出完成固定工具链重建、API/导入审查并更新审核清单；详见 `native/startouch/REPRODUCIBLE_BUILD.md`。这只清除二进制来源门，HOME、TCP/抓取偏移和放置路径仍须现场实测，执行保持关闭。

## 测试顺序

1. 先写失败测试：运行时篡改/多余文件、CAN 回环/缺 ID、3° 余量、cleanup 语义和握手身份。
2. 实现项目内安全运行时与 Python 桥接门禁。
3. 实现 Node 配置/工厂/协议的身份绑定和如实 cleanup 回执。
4. 运行安全模块、协议集成和全量离线回归。
