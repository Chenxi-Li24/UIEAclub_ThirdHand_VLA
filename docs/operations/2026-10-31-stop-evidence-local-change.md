# 停止回执本地修复：不再将 SDK 释放等同于物理停止

对应 [外网运动实施计划](../superpowers/plans/2026-10-31-remote-motion-readiness.md) 任务 3。本记录只涵盖本地实现和无硬件测试；**没有部署、连接 SDK、发送 CAN 或执行真实停止/运动试验，硬件停止能力尚未验收。**

## 根因与修复

原 Python `disconnect()` 在 `arm.cleanup()` 抛错后仍释放独占控制锁、发出 `connection:false`。Node 又把 `reason=software_stop` 的断开事件无条件转成“停止完成”，Controller 随后报告 `stopped:true`、`depowered:true`。这只能证明软件路径走到了断开回执，不能证明机械臂停止或电机失能。

本次修改：

- Python 回执新增 `request_id`、`sdk_released`、`cleanup_state`、`stop_state`、`stop_code`、`source_mode`。普通 cleanup 成功仍报告物理 `stop_state=unknown`；失败使用固定错误码，不输出 cleanup 异常的任意文本。
- cleanup 失败时保留原控制锁和待释放 SDK 对象，拒绝再次 connect；只有显式释放重试成功才能解除该软件锁。SDK 构造/状态初始化失败后的 cleanup 失败同样处理。
- Node 将 SDK 释放回执改为 `software_stop_result`。硬件回执没有可信硬件反馈时为 `STOP_UNCONFIRMED`，不报告停止或失能。旧 `software_stop_complete` 名称不再成为物理停止依据。
- 关联请求的超时、SDK worker 退出都产生 unknown 回执；worker 退出同时发布通用 connection 消息，使执行实例与状态订阅能观察失联。旧 worker 的退出不能影响新 worker。
- 正在处理的 stop 保留原 requestId 和定时器，匿名并发停止不重复发送；不同显式请求返回关联的 unknown，不抢用旧停止证据，也不覆盖原命令。
- 模拟模式保留模拟取消结果，并明确 `sourceMode=simulation`、`depowered=false`；不能据此验收真实停止。

只读设备的专用结果仍应叫“SDK 连接已释放”。新版 `sdk_released=false` 必须阻止把失败的 cleanup 当作只读成功；由根任务在 remote-gateway 中集成，不在本次子任务修改 gateway。

## 停止证据验证接口

新增 `services/robot/src/stop-evidence.js`：

```text
validateStopEvidence(evidence, currentContext, stopProfile) ->
  {ok:false,code} 或 {ok:true,code:'STOP_VERIFIED',depowered,coverage}
```

该函数第三参数代码变量名为 `limitsProfile`，实际传入的是**独立停止参数 profile**，不能以运动限位摘要代替停止参数摘要。输入结构：

- `currentContext`：`commandId`、`executorEpoch`（UUID），`hardwareFingerprint`（hex64），`now`（整数 UTC 毫秒）。
- `stopProfile`：`digest`（停止参数摘要，hex64）、`stop`。`stop` 必须明确提供 `maxStopTimeMs`、`maxFeedbackAgeMs`、`maxVelocityRadS`、`maxJointDeltaDeg`、`minStableDurationMs`、`minSamples`、`requiresDisabled`、`includesGripper`；涉及夹爪时还需 `maxGripperVelocityMmS`、`maxGripperDeltaMm`。无默认硬件阈值。
- `evidence`：同一 `commandId/executorEpoch/hardwareFingerprint`、`requestedAt`、`observedAt`（毫秒），`state='stopped'`、稳定错误码形式的 `reason`，以及 `measurement`。
- `measurement`：`kind='hardware_feedback'`、`sourceMode='hardware'`、`profileDigest`（hex64），六轴 `jointVelocitiesRadS` 和 `jointDeltaDeg`、`sampleCount`、`stableDurationMs`、`driversDisabled`；覆盖夹爪时必须有 `gripperVelocityMmS/gripperDeltaMm`。

拒绝错误命令/实例/指纹、旧/未来时间、未知/模拟来源、cleanup 代替反馈、缺参数、稀疏/缺轴/非有限数组、单个瞬时零速样本、速度/余动超标、所需失能状态未确认及夹爪缺反馈。反馈年龄最多 500 ms，稳定窗口须在本次请求之后并满足已核定阈值。

验证器只校验语义，**不是证据认证或硬件测量器**。调用者必须保证证据来自可信本机反馈适配器、profile 来自经过核定的设备配置；网页传入同形 JSON 不构成证据。本次没有实现或伪造实际硬件证据生产者。`depowered` 只对返回的 actuator coverage 有效。

## 硬件能力的资料边界

本地 `local/generated/startouch-python/startouch_sdk/interface_py/startouchclass.py` 的 `cleanup()` 仅转调底层 `self.arm.cleanup()`。本地 SDK 头文件只见接口声明，无法由此核验六轴独立看门狗及驱动失能反馈。

`local/sdk/startouch/README_API.md` 的中断示例明确把 cleanup 用于进程退出处理，并要求立即停机依赖硬件急停。现有资料不足以证明 Robot/SDK 失效时能独立达到停止要求；源码说明也不等于已运行二进制的现场证据。因此硬件运动门禁继续关闭。

## 测试证据

- 新停止 Node 测试 13/13：行为 RED→GREEN，覆盖误报、请求关联/并发、超时/进程退出、证据新鲜度/稳定窗口、夹爪及缺轴数据。
- Robot Service 原有 38 项无硬件测试，加本次 13 项，共 **51/51**，无跳过；Node 24.22.1。测试需要本机回环 WebSocket，沙箱内连接拒绝后在获准本机网络环境复核。
- Python 新停止 5 项、固定 TCP 桥接及关节速度专项，共 **28/28**；使用既有 `edge-test-env`，没有导入或构造真实硬件 SDK。
- Python `git apply` 夹具需在 Git 仓库外的临时目录运行。放在仓库内会因 Git 前缀语义产生虚假失败；最终使用获准外部临时目录重跑通过。未用跳过断言处理该环境问题。

证据均在本计划忽略目录 `.superpowers/sdd/2026-10-31-remote-motion-readiness/stop-evidence/`：`node-red.txt`、`python-red.txt`、`validator-red.txt`、`worker-exit-red.txt`、`profile-hex-red.txt`、`sparse-feedback-red.txt`、`stop-concurrency-red.txt`、`node-final-regression.txt`、`python-regression-external-temp-approved.txt`。

修改文件为三个桥接/Controller 源文件、新 stop-evidence.js、Node/Python 对应测试及本记录；未修改 server、remote-gateway、control-policy、设备限位或运行配置。没有 Git commit/push。
