# ThirdHand Device Data and Control Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans after plan review. Steps use checkbox (`- [ ]`) syntax for tracking. This document does not authorize hardware motion or production deployment.

**Goal:** 建立设备身份、双向中继、控制权、完整数据和受保护相机，先用模拟设备验收。

**Architecture:** Node 云端中继与人员业务服务分模块，首期同一部署组合；Python Agent 只调用 Ubuntu 本机 Robot Service，SQLite outbox 与 PostgreSQL 事务确认配合。生产媒体使用独立 WebRTC 服务，不经控制通道搬运视频帧。

**Tech Stack:** Node.js 24/pg/ws、Python 3.11/websockets/sqlite3/cryptography、Ed25519、mTLS、PostgreSQL range 排除约束；视频选用独立部署的 LiveKit SFU 与设备发布适配器，资源和网络通过 C 阶段压测后才准入真机。

**Spec:** [设计 v0.4.1](../specs/2026-10-29-public-access-roles-database-design.md)；[总计划](2026-10-30-public-access-rollout.md)；依赖 [A1 仓储与 A3 权限](2026-10-30-login-identity-workspace.md)。

## Global Constraints

继承总计划全部约束。观察员仅有读通道与本地模拟；设备上线、重连、采样订阅不能 connect SDK。设备签名密钥与人员 Cookie 分离，证书、密钥、真实执行令牌不进浏览器或 Git。所有 B 任务先在 FakeRobot 与隔离数据库运行，现场验证另见 C3。

## Review Focus

设备证书与执行实例不一致由 B1/B2 验证；浏览器已失联而 Agent 正常由 B3 验证；命令确认丢失由 B2/B3 验证；跨批次重叠与 outbox 满由 B4 验证；退出仍看视频或回放发真命令由 B5/B6 验证。

## 共用协议边界

- `DeviceContext={deviceId,bootId,executorEpoch,certificateId,connectionId}`：由受控证书与设备握手建立，不接受浏览器自行填写身份。
- `Lease={id,deviceId,sessionId,clientInstanceId,bootId,executorEpoch,epoch,state}`：A3 Principal 通过权限后申请；只有设备确认的 active 记录能发送普通动作。
- `SignedEnvelope={keyId,payloadBase64url,signatureBase64url}`：云端用 Node crypto Ed25519 签署原始 UTF-8 payload 字节；Python 验证同一字节后才解析，不能在跨语言重新序列化浮点参数后验签。
- payload 固定包含 schema、命令 ID、目的设备、boot/执行/控制代次、序号、操作码、参数、签发与过期时间；不接受任意 SDK 方法、shell 或代码。
- 普通动作必须有当前控制权；跨持有者的软件停止是独立 purpose，仍要求当前管理员模式/MFA、设备与执行实例、短期有效签名，不进入普通忙队列。
- 设备事件与采样使用源时间、序号和入库确认；控制请求不在断线后补发。原命令结果不明时返回 unknown 并核对状态。

## B1 设备身份、mTLS 与无硬件中继

**Files:** 新增 `services/device-relay/package.json`、`src/server.js`、`registry.js`、`envelope.js`、`protocol.js`；新增 `platform/contracts/schemas/remote-device.schema.json`、`remote-command.schema.json`；新建 `services/edge-agent/pyproject.toml`、`src/thirdhand_edge/transport.py`、`protocol.py`；测试 `tests/node/public_access/device-relay.test.js`、`tests/python/edge_agent/test_transport.py`。

**Interfaces:** `createDeviceRelay({store,identity,clock}) -> {server,devices,close}`；`devices.send(deviceId,envelope)`；`verifyEnvelope(bytes,keyId,signature)`；Python `async connect_device(config,on_message)`。设备端点 `/edge/v1/connect`，无敏感探针 `/edge/v1/healthz`，须先经设备证书认证；云侧开发监听 127.0.0.1:3201。

- [ ] 写设备注册与 WSS 测试：有效证书只能代表绑定设备；未知、过期、撤销证书拒绝；伪造内部证书头拒绝；重连更换 connectionId，不继承旧授权。
- [ ] 运行 `node --test tests/node/public_access/device-relay.test.js` 和 `python -m pytest -q tests/python/edge_agent/test_transport.py` 确认预期红灯。
- [ ] 实现 mTLS 入口信任边界、协议验证、设备注册/撤销和仅 ping/pong 的 Agent；代理证书只能来自受信任本机 Nginx，TLS 配置可注入隔离测试 CA。不得为探针导入 SDK、访问 CAN 或采集视频。
- [ ] 重跑绿灯，用临时证书与模拟设备完成双向心跳；云端签名与 Python 验证做交叉测试，篡改任何 payload 字节、keyId 或目的设备均失败。依赖版本锁定，不把测试私钥带到生产。

## B2 本地适配、执行代次与停止

**Files:** 新增 `services/edge-agent/src/thirdhand_edge/robot_client.py`、`command_gate.py`、`journal.py`；新增 `services/robot/src/control-policy.js`、`lease-watchdog.js`；修改 `services/robot/src/server.js`、`robot-controller.js`、`config.js`；测试 `tests/python/edge_agent/test_command_gate.py`、`tests/node/public_access/robot-control-policy.test.js`。

**Interfaces:** Python `async handle_envelope(envelope,device_context,robot_client,clock) -> CommandOutcome`；Robot `validateControlContext(message,executionState) -> {ok,code}`；`LeaseWatchdog.renew(context)`、`expire()`。`CommandOutcome` 严格区分 accepted/started/completed/stopped/rejected/failed/unknown；去重 journal 先持久记录后提交 SDK。

- [ ] 写 FakeRobot 测试：上线、订阅状态、重连均无 connect；错误签名、旧 boot/执行/控制代次、重复序号和过期命令调用计数为 0；相同命令确认丢失不能再次提交。
- [ ] 写 Robot 侧测试：500 ms 状态新鲜度保持；停止走优先路径；Agent 进程死亡不使 Robot 永久保留授权；SDK worker 重建、CAN 配置变化时撤权，新执行实例未经核验不能运动。
- [ ] 运行上述两个测试文件红灯后实现门禁、原协议适配与 journal。授权超时监督放在独立于 Agent 的 Robot 执行层，不能只靠 Agent 自己通知停止；SDK 阻塞或更低层失效的独立停止能力列为 C3 硬件准入，不伪称杀进程即安全停止。
- [ ] 重跑绿灯；测试旧 `/ws`、`/execution`、Dummy、语音和本机 CLI 在远控配置下不能绕过设备仲裁。维护模式仅由受控本机配置/OS 身份进入，不能通过外来 JSON 布尔值开启。

## B3 控制权、接管与端到端续期

**Files:** 新增 `services/cloud-api/src/control/leases.js`、`takeovers.js`、`control-channel.js`、`dispatcher.js`、`routes/control.js`；新增 `platform/storage/src/leases.js`；新增 `services/edge-agent/src/thirdhand_edge/lease.py`；更新 B1/B2；测试 `control-leases.test.js`、`takeovers.test.js`、`control-heartbeat.test.js` 在 `tests/node/public_access/`。

**Interfaces:** `requestLease(principal,{deviceId,clientInstanceId})`；`requestTakeover(principal,{deviceId,targetEpoch})`；`confirmTakeover(principal,{requestId,nonce})`；`renewFromBrowser({principal,connectionId,challenge,sequence})`；`revokeLease({leaseId,reason})`；`dispatchRealCommand(principal,{deviceId,leaseId,command}) -> Promise<CommandReceipt>` 位于 dispatcher.js，检查控制持有者后再签发并发送。通过 A3 authorize，使用 B1 devices 与 B2 Outcome；真实派发仅允许 active context。

- [ ] 事务测试：两人/两个标签页竞争仅一人成功；第二管理员登录不撤销别人控制；接管必须提示并绑定当时 targetEpoch；停止未确认、目标已变、申请人退出均不得授新权。
- [ ] 假时钟测试：浏览器每 250 ms 响应，云端要求最近 500 ms 有有效响应；云到设备正常但浏览器失联时不能代续，设备本地期限 1 s 到达撤权；重复挑战与旧连接重连不恢复。
- [ ] 运行 `node --test tests/node/public_access/control-leases.test.js tests/node/public_access/takeovers.test.js tests/node/public_access/control-heartbeat.test.js` 红灯后实现云/设备双确认、角色撤销联动、代次与优先停止；数据库不可写拒绝新动作，停止不依赖数据库成功。
- [ ] 重跑绿灯；验证退出/模式下降、账号停用和 MFA 失效都会影响既有控制通道。以模拟设备演示未知结果和接管失败，界面不得显示未发生的“已停止”。

## B4 原始数据、outbox 与跨批次去重

**Files:** 新增 `services/edge-agent/src/thirdhand_edge/outbox.py`、`telemetry.py`、`upload.py`；新增 `services/cloud-api/src/routes/ingest.js`、`platform/storage/src/ingest.js`；测试 `tests/python/edge_agent/test_outbox.py`、`tests/node/public_access/ingest.test.js`；补 A1 数据迁移和 CI 数据库任务。

**Interfaces:** Python `append_sample(sample)`、`seal_batch(stream) -> ImmutableBatch`、`ack_batch(id,digest)`；Node `ingestBatch(deviceContext,batch) -> {batchId,digest,persisted}`。批次按设计唯一 ID、连续序号范围与摘要定稿；事务同时写账本、有效样本及 invalid_samples。

- [ ] 写测试：进程重启后未确认批次仍在；网络收包未提交数据库不回收本地；相同批次相同摘要不重复写；同序号不同时间、新批次、部分范围重叠或并发上传由数据库拒绝。
- [ ] 写数据与容量测试：目标与实测分开，原始源发布率不因观察员身份减少；单位、坐标/工具版本、采集/接收时间可追溯；outbox 接近满产生告警与缺口，不阻塞停止通道或静默丢弃。
- [ ] 运行 `python -m pytest -q tests/python/edge_agent/test_outbox.py`、`node --test tests/node/public_access/ingest.test.js` 红灯后实现 SQLite WAL 缓冲、不可变批次、优先事件和 PostgreSQL range 排除约束；日志禁止凭据，未批准前不自动删除历史。
- [ ] 重跑绿灯，断网模拟不少于多个批次并恢复补传；按实际配置频率和一小时样本测量存储增幅、索引与 WAL，回填容量报告，不能仅按 10 Hz 设计例子采购或上线。

## B5 完整历史、导出与模型回放

**Files:** 新增 `platform/storage/src/history.js`；新增 `services/cloud-api/src/routes/history.js`、`exports.js`、`jobs/export-worker.js`；新增 `apps/web/public/history.html`、`js/history-page.js`、`js/history-replay.js`；测试 `history.test.js`、`exports.test.js`、`history-replay.test.js` 在 `tests/node/public_access/`。

**Interfaces:** `queryRuns(principal,filter,cursor)`、`querySamples(principal,filter,cursor)`；`createExport(principal,filter) -> job`；`openExport(principal,jobId)`；前端 `createHistoryReplay({armModel,samples,versions})` 只用 A5 模拟通道。

- [ ] 写测试：观察员可读其他用户动作及全部源采样、错误、维护记录；不能读邮箱列表、安全凭据和登录日志；游标翻页合并无丢样/重复；聚合图可返回原始数据；跨时区查询有明确 UTC 边界。
- [ ] 写导出与回放测试：大型导出异步有并发/大小限额且不截断数据；私有对象下载再验当前会话；过期/退出拒绝；历史播放真实命令调用次数为 0；缺口不伪插为实测值。
- [ ] 运行 `node --test tests/node/public_access/history.test.js tests/node/public_access/exports.test.js tests/node/public_access/history-replay.test.js` 红灯后实现分页、工作线程/任务、私有导出和版本化回放；不把整个表一次读入内存。
- [ ] 同一命令绿灯，核对 CSV/JSON 与原库采样总数、摘要和单位；设计默认没有录像任务，不能把导出文件清理误做原始历史删除。

## B6 相机、媒体授权与语音入口

**Files:** 新增 `services/cloud-api/src/media/livekit-provider.js`、`routes/media.js`；新增 `services/edge-agent/src/thirdhand_edge/media_publisher.py`、`frames.py`；新增 `apps/web/public/js/camera-view.js`；更新 `apps/web/public/js/voice-control.js` 与 A3 长连接权限接入；测试 `media-policy.test.js`、`voice-mode-policy.test.js` 和 `tests/python/edge_agent/test_frames.py`。

**Interfaces:** `issueViewGrant(principal,{deviceId}) -> shortLivedGrant`、`revokeViewers(sessionId)`；`FrameSource.getLatestFrame() -> {rgb,capturedAt,sequence,quality}`；`VideoHealth.isFresh(deviceId,now)`。管理员语音入口使用相同 Principal，动作候选执行仍走 B3，不能直接调用 RobotProxy。

- [ ] 写授权测试：两角色只能获订阅视频授权，观察员无发布/麦克风/语音/真机权限；登出、停用立即撤销观看会话；令牌限定设备，不能借查看权限管理媒体服务。
- [ ] 写时效与复用测试：订阅观看不会新建机械臂 SDK 连接；复用现有相机采集而非每观众重新开硬件；保留真实采集时间与接收时间区别；视频过期或状态不明时禁止新动作，持续控制按策略停止。
- [ ] 运行 `node --test tests/node/public_access/media-policy.test.js tests/node/public_access/voice-mode-policy.test.js` 和 `python -m pytest -q tests/python/edge_agent/test_frames.py` 红灯后实现媒体适配、权限撤销和状态指示；先用合成帧，生产摄像流在明确部署阶段接入。
- [ ] 绿灯后在隔离媒体环境测试单路发布/多人分发、UDP 与 TURN/TLS、延迟和退出撤销；不能用 MJPEG 能显示或客户端自报 cameraReady 就认定满足真机远控条件。

## B 阶段完成条件

- [ ] CI 实际执行全部新增测试，FakeRobot、隔离 PostgreSQL 与合成媒体能完整演示；没有“测试未配置却当通过”。
- [ ] 运行数据和模拟数据分离；审阅证书绑定、命令签名、端到端续期及停止策略；未通过 C3 不开放真实 SDK 入口。
- [ ] 将实测容量、传输延迟和媒体资源报告交给部署阶段，不自动购买或变更云资源。

## 依赖技术参考

- [node-postgres 连接池](https://node-postgres.com/features/pooling)
- [Python cryptography Ed25519](https://cryptography.io/en/latest/hazmat/primitives/asymmetric/ed25519/)
- [LiveKit 自托管部署](https://docs.livekit.io/transport/self-hosting/deployment/)

这里选择的库与媒体适配是实施层选择；若目标网络、许可或资源不满足，先报告并修订对应计划，不将未经压测的媒体方案强行接入真机。
