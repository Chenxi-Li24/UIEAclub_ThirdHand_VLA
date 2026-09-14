# Startouch 方案 A 实施计划

**目标：** 将 Reuse 的受控 Startouch 运行时和安全证据链适配到 Pin 现有 JSON-lines/法兰位姿协议，并保持真机闭锁。

**规范：** `docs/superpowers/specs/2026-08-24-startouch-safety-hardening-design.md`

## 任务 1：受控 SDK 运行时

- 新增 `native/startouch/vendor_runtime.py` 和 `native/startouch/startouch_source.json`。
- 新增离线准备脚本，运行时只能输出到本项目 `build/startouch_runtime/startouch_sdk`。
- 测试安全配置精确值、资产哈希、多余文件、本地库映射和可复现来源标志。

## 任务 2：Python 真机启动门禁

- `SdkBackendConfig` 改为接收已验证的项目内运行时。
- 导入 SDK 前校验运行时资产、安全配置哈希和可复现来源。
- 以被动 SocketCAN 观察器替换 `rx_packets` 计数，丢弃本机回环，要求 `0x11..0x17`。
- 启动状态和每次运行期状态读取均执行关节限位与 3° 余量校验。

## 任务 3：cleanup 与协议语义

- 真实后端只回传 cleanup 已返回，永不声明独立掉电。
- 握手模式更改为 `cleanup_ack_only`；完成事件显式包含 cleanup 与 depower 字段。
- 工作流和 HOME 协调器将 cleanup 回执视为“已终止 SDK 控制并断开”，但不视为硬件掉电证明；回执缺失仍失败闭锁。

## 任务 4：Node 配置与身份绑定

- `action.yaml` 新增 `runtime_root`、`source_manifest`、`safety_profile_id`、`safety_config_sha256`、`joint_limit_stop_margin_deg`。
- 工厂只向桥接传递项目内运行时参数，不再传外部 `sdk_path`。
- 程序客户端校验安全剖面、配置哈希、运行时清单 ID 和启动 CAN ID。
- 现有 HOME 候选进入 3° 余量时，非激活配置可加载但保持闭锁；`execution_enabled=true` 必须拒绝。

## 任务 5：离线验证与文档

- 顺序运行失败测试、安全运行时测试、Python/Node 协议集成测试。
- 运行 Pin 项目全量 Python 与 Node 离线回归。
- 更新依赖/调试文档和受监督验收前置。后续已完成 CPython 3.10 双份干净构建及 API/导入审查；二进制来源门已清除，但 HOME、TCP/抓取偏移、放置路径和执行开关仍闭锁。
