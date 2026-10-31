# ThirdHand 外网真机运动修复实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. 用户已选择在本会话逐项实施、阶段结束后复核；本轮随后明确批准可并发进行的工作，独立源码、测试与审阅已按互斥文件范围分工。远端部署及任何硬件操作均由主任务串行执行。

**Goal:** 修复连接与视频故障，补齐实际停止、设备绑定和受限运动验证，使管理员能在 staging 通过外网完成真实六轴与夹爪验收，且结果可在网页查询、导出。

**Architecture:** 延续云端业务后端、私有 PostgreSQL、Ubuntu 主动连接的结构。控制续期、媒体授权、实时状态、历史补传相互隔离；真实运动由云端权限与 Ubuntu 本机保护共同决定。先证明只读通道稳定，再开通仅限指定管理员、指定设备、指定范围的短期运动验收配置。

**Tech Stack:** 现有 Node.js 24、Python 3.11、mTLS/WSS、LiveKit、SQLite outbox、PostgreSQL、Nginx/systemd；不在本轮升级框架或新增公网端口。

**Spec:** [角色与数据库设计](../specs/2026-10-29-public-access-roles-database-design.md)、[设备控制子计划](2026-10-30-device-data-control.md)、[现场预检](../../operations/2026-10-31-C3b-motion-preflight.md)。

## Global Constraints

- 工作目录 `D:/claudeworkplace/thirdhand-login`、分支 `login`；保留当前未提交工作。开始时记录 HEAD、文件差异和远端状态；不同步覆盖 Ubuntu 现场修改，不对本轮混入无关功能。
- 用户已允许 J1–J6 协同及 J7 夹爪，六轴相对本次实测起点均不超过 20°，且不得超过真实限位。20°是上限，不是首次测试目标；夹爪用 mm/% 单独规定，不能换算成“20%”。
- 现场看护、清场、急停可用已确认。真正开始运动时确认本轮现场状态仍有效；长时间排障后的旧确认不当作永久现场保证。
- 观察员继续只能观看、读历史和操作 Three.js；管理员登录不自动抢占控制权，SDK 不自动连接，恢复网络不恢复动作，未知结果不自动重发。
- 现有浏览器挑战有效期/Robot 状态新鲜度 500 ms、本机控制期限不超过 1 s、媒体签名期限不超过 1 s 保持；不能仅延长时限掩盖超时。
- 采集时间、接收时间、入库时间分开；历史数据库样本不用于实时运动门禁，进程退出或 SDK cleanup 成功不单独证明实际停止。
- 原始采样、命令和事件持续入库，不以减少原始数据或改观察员权限掩盖延迟；密钥、MFA、Cookie、邮件密码不进入日志或 Git。
- 部署前给出确切文件/路由/服务/迁移差异、哈希、备份和回退，再按既定实际配置审阅流程应用；用户的现场运动许可不替代未知服务器变更清单。
- 本轮不自动开放 Home/Zero、固定动作序列、语音、抓取或其他后台 SDK 路径；教程沿用队友接口，真实集成状态如实记录。

## Review Focus

1. 工具切换标签页、窗口最小化、CPU 阻塞、网络停顿都可能造成 browser_stale：记录真实原因，隐藏/失联后撤权，不制造后台自动代续；任务 1、6 验证。
2. 相机可看但帧已过期、来自另一设备或时间误差未知：观看与允许运动分别判断，假“实时”不能获得控制；任务 2、5 验证。
3. SDK 断开、cleanup 异常、状态不可读与实际停止不同：unknown 阻止新动作和接管，不能展示“已失能”；任务 3 验证。
4. J2 实测 −12.21°与默认下限 −12°不一致：核对坐标、偏置与设备规格，不扩限或直接夹紧到边界；任务 4 验证。
5. 回退/重连/进程重启不能复用原执行实例、控制权或测试范围：旧证据失效，历史保留，动作不重放；任务 5、7、8 验证。

## 任务 0：冻结实施基线与运动范围

**Files:** 更新本计划；新增 `docs/acceptance/remote-motion-session.md` 记录表；后续部署审阅写入 `docs/operations/2026-10-31-C3c-motion-deployment-review.md`。此阶段不改运行配置。

**Interfaces:** `MotionScope={deviceId,administratorId,sessionId,baselineSequence,baselineDeg[6],maxDeltaDeg:20,gripperRange,limitsDigest,expiresAt}`。实测起点、夹爪范围和过期时间须在实际测试时填写，不预填旧数据。

- [x] 记录当前 Git 差异、云端 current 指向及活动服务、Ubuntu 源码/SDK/配置公开摘要；包含当前 C5 发布 `6187bbbe8ec4d5e8`，执行时重新核验。
- [x] 记录只读设备与独立相机身份；保存不含凭据的预检 JSON，区分只读接入通过和运动准入通过。
- [x] 将六轴 ±20°上限、夹爪 mm/% 待现场确定、首步小幅试验写入记录表；未有新实测起点不得生成真实目标。

**通过条件：** 可回到同一发布与只读服务；授权范围可追溯，未新增硬件动作。

## 任务 1：定位并修复控制续期、相机授权超时

**Files:** 修改 `services/cloud-api/src/control/{control-channel,websocket,leases}.js`、`services/device-relay/src/server.js`、`services/edge-agent/src/thirdhand_edge/{bound_transport,media_upload,media_publisher,camera_runtime}.py` 中实际根因涉及的文件；新增 `tools/diagnostics/control_timing_probe.py`，不同时盲改全部模块。

**Interfaces:** 公共诊断 `TimingEvent={traceId,stage,elapsedMs,queueMs,outcome,contextDigest}`；stage 固定为 browser_challenge/browser_response/cloud_dispatch/edge_receive/local_ack/cloud_ack/media_request/media_ack。各主机用单调时钟测区间；跨主机不直接相减未经校准的单调时间。不得输出签名原文、令牌或私钥。

- [ ] 先加诊断，分别测浏览器→云、云→Ubuntu、Ubuntu→Robot、媒体 HTTPS、PostgreSQL 等待及进程事件循环阻塞；覆盖真实外网前台标签页、切后台及只读采集并发。
- [ ] 为实际复现的故障补失败测试：挑战 ACK 迟到、续期并发/乱序、数据库慢、媒体响应丢失、源读取阻塞。断言旧响应不能复活授权，媒体失败仍在原期限内停播。
- [ ] 依证据修根因：若队列阻塞则拆独立执行/优先队列；若共享连接造成队头阻塞则分离连接；若挑战调度/绑定错误则修状态机。网络本身超过预算时报告不达标，不自动放宽期限或宣称软件已修复网络。
- [ ] 新诊断先本地/模拟验证，再按具体差异审阅部署到 staging，仍只读；连续观察 30 分钟，同时保持两个真实观看者与只读采集。自然失联为 0、签名/挑战按原有效期验证；记录 P50/P95/P99/最大值与重传，任何未解释的失联都不进入运动。
- [ ] 在无运动条件重做已批准范围的 35 秒视频管理链路故障测试；新版本规则须有独立自动恢复，停播、撤销、恢复后重新授权均有同期证据。

**测试：** `node --test tests/node/public_access/control-heartbeat.test.js tests/node/public_access/control-websocket.test.js tests/node/public_access/control-leases.test.js`；`python -m pytest -q tests/python/edge_agent/test_media_upload.py tests/python/edge_agent/test_frames.py tests/python/edge_agent/test_camera_runtime.py`。

**通过条件：** 修复有根因和回归证据；持续运行及故障恢复均通过，不能只“重启后看见一次视频”。

## 任务 2：补齐可信画面时间和相机—机械臂关联

**Files:** 修改实际 Vision 采集/发布适配器、`services/edge-agent/src/thirdhand_edge/{frames,camera_source_gate,runtime}.py`、`services/cloud-api/src/media/policy.js`、`apps/web/public/js/camera-view.js`；新增 `services/cloud-api/src/media/motion-video-bridge.js` 和对应测试。

**Interfaces:** 保留 `FrameEvidence={frameId,capturedAtUs,clockQuality,uncertaintyMs}`。新增 `createMotionVideoBridge({mediaService,bindings,signer,clock})`，方法 `issue({robotContext,cameraContext}) -> signedMotionVideoHealth`；新签名 purpose 为 `motion_video_health`，绑定完整 robot context、camera context、当前帧及期限，不包含媒体 JWT。该证据只证明绑定源画面的时效；操作者实际解码条件由云端 `videoReadiness(principal,deviceId)` 在任务 5 独立检查。

- [ ] 核验相机 SDK 是否提供可关联的硬件采集时间；测量时钟映射、缓存和误差。只能取得接收时间或无法给出误差上界时保留 unreliable、禁止运动，不将时间字段换名冒充采集时间。
- [ ] 为旧帧、倒序帧、时钟跳变、误差超限、相机换机、旁观者帧 ACK 补失败测试；从实际采集边界透传元数据，不能在云端收到 JPEG 时补造。
- [ ] 相机保留独立凭据与观看服务；建立经现场核验的 robotDeviceId↔cameraDeviceId 绑定及版本。当前操作者须实际解码并 ACK 对应帧，其他观察员的观看不能代其满足运动条件。
- [ ] motion-video-bridge 核验相机绑定、源帧时效和机械臂执行实例，再签发短期健康证据；本机只接受当前 context 的该 purpose。源证据可以在尚未申请运动控制权时建立，不能因此授予控制权；相机令牌本身不能用于真机命令。
- [ ] 明确区分网页“可观看”“画面时间未知”“画面过期”“满足本次运动条件”；源帧年龄加误差不超过 500 ms，任何环节未知则拒绝新运动。

**测试：** 现有 `media-policy.test.js`、`camera-view.test.js`、`test_frames.py`；新增 `motion-video-bridge.test.js`；真实页面核对本机 videoHealthy、云端 sourceFresh、当前操作者帧 ACK 的同一帧证据。

**通过条件：** 可以证明看到的是本机械臂当前画面；视频故障会撤销运动条件，相机观看权限保持原边界。

## 任务 3：修正停止回执并验证独立停止路径

**Files:** 修改 `services/robot/src/{startouch_bridge.py,startouch-bridge.js,robot-controller.js,remote-gateway.js,control-policy.js,lease-watchdog.js}`；新增 `services/robot/src/stop-evidence.js` 及 `tests/node/public_access/stop-evidence.test.js`；Python 桥接停止测试放入 `tests/python/robot_service/test_remote_stop_evidence.py`。

**Interfaces:** `StopEvidence={commandId,executorEpoch,hardwareFingerprint,requestedAt,observedAt,state,measurement,reason}`；state 为 stopped/unknown/failed，measurement 明确实际速度/位置、驱动状态与测量时间。`validateStopEvidence(evidence,currentContext,limitsProfile) -> {ok,code}` 只认可同一当前执行实例的真实反馈。

- [x] 先补失败测试：cleanup 抛错、进程消失、connected=false、超时、陈旧反馈都不能直接产生“电机已失能”；只读模式仍明确返回 SDK 已释放，不冒充物理停止。
- [x] 将停止请求接收、SDK 清理完成、实际速度归零/保持及驱动失能分开记录；不得在没有反馈时把 stopped/depowered 写 true。
- [ ] 核对设备支持的受控停止、保持和独立看门狗方式，明确断电下坠与夹爪松脱风险。若现有硬件无法在 Robot/SDK 故障时独立达到停止条件，应先补齐硬件能力；杀进程不能替代它。
- [ ] 现场先静止验证急停/保持与反馈，按设备规范确定并记录停止时间、允许余动与反馈噪声阈值；阈值必须在运动前写入本次记录，不用未经实测的统一数字作安全承诺。
- [ ] 再在单独的小幅试验阶段测本地停止与失联停止。停止未确认保持 unknown，拒绝新控制权、接管和动作，交由现场处理；不自动重连。

**通过条件：** 云端、Agent、Robot 和 SDK 的停止回执语义一致，实际停止时间有现场证据；独立急停保持有效。此项未通过不开放远控运动。

## 任务 4：核实设备限位并加入本轮运动范围限制

**Files:** 新增 `services/robot/src/motion-session-policy.js`、`tests/node/public_access/motion-session-policy.test.js`、版本化设备限位配置；修改现有 `motion-policy.js`、`config.js`、`control-policy.js` 和 Python 桥接中的对应检查。

**Interfaces:** `validateMotionSessionTarget({scope,currentState,targetDeg,timeSec,limitsProfile,now}) -> {ok,code}`。scope 使用任务 0 的定义；limitsProfile 包含物理限位、坐标/偏置版本、速度/加速度配置及夹爪有效范围，其摘要须与现场绑定一致。

- [ ] 根据真实设备规格及原 SDK 配置核对 J1–J6 的方向、零点、单位、软件/物理限位；专项解释 J2 −12.21°与 −12°差异。不能仅为通过测试扩大限位或把起点夹紧到边界。
- [x] 补失败测试：相对基准超过 20°、分多次累积逃出范围、当前状态超过 500 ms、NaN/缺轴、旧 session、限位版本变化、速度超限、夹爪非法量；全部在 SDK 调用前拒绝（本地模块验证，真实执行入口接线仍属任务5）。
- [ ] 本机保存同一新鲜实测起点，六轴目标均同时通过物理限位与相对起点 ±20°约束；协同运动检查中间路径和末端空间，不能只检查终点。
- [ ] 设置本轮低速/加速度上限、单次时长与停止判据，生成明确轨迹预览。首次六轴试验拟从不超过 2°的小幅协同开始，只有通过后才评估更大幅度；20°不是必须达到的目标。
- [ ] 夹爪现场确定测试开合量与夹持区域，校验 SDK 的 mm/% 转换和能力；先单独验证，再评估能否与六轴并发。未证明支持原子并发时不承诺七个执行器严格同时起动。

**通过条件：** 新鲜起点、限位及路径一致，设备端有不可由网页滑条绕过的本轮范围限制；夹爪单位和幅度明确。

## 任务 5：接通可核验的运动准入与独占控制

**Files:** 新增 `services/robot/src/hardware-acceptance.js`；修改 `server.js`、`remote-gateway.js`、云端 `device-runtime.js`、控制 leases、设备 registry/relay；仅在现有表不能容纳范围/证据时增加最小迁移（当前 001–009，新增使用 010），保留既有只读凭据。

**Interfaces:** `MotionAcceptance={deviceId,bootId,executorEpoch,hardwareFingerprint,limitsDigest,stopEvidenceId,scopeDigest,acceptedBy,expiresAt}`；`createHardwareAcceptance({getExecutionState,loadEvidence,clock}).isAccepted() -> boolean`；加载的证据须由受控本机核验流程产生，网页不能直接提交 accepted:true。

- [ ] 为错误设备/证书、旧执行实例、旧停止证据、已过期范围、模式降级、撤销账号、两个标签页竞争补失败测试。
- [ ] 将执行实例握手、允许连接 SDK、允许运动三种检查分开，补首次冷启动测试：握手不能等待仅在 bound_ack 后才可能产生的媒体回执，connect 不能等待尚未连接的 SDK 状态；缺少 MotionScope 或新鲜状态时仍禁止运动。任务 1 的只读连接作为 commissioning 输入，不能从握手成功推导运动已就绪。
- [ ] 本机实际接入 hardwareAccepted 与 initialStopVerified 的验证逻辑，启动、SDK worker 重建、CAN/限位配置变化均使旧证据失效。处理首次接入的顺序：先在只读流程核验静止状态/停止证据，再绑定当前 executor，不复用另一个实例的 PID 指纹或状态。
- [ ] 云端 readiness 从“readOnly 即通过”扩展成明确的只读/连接检查与受限运动检查；运动分支同时检查管理员模式/MFA、有效范围、新鲜 SDK 状态、本机绑定/停止/记录健康与任务 2 的当前操作者视频条件。dispatch 按操作码调用相应检查，不以 connect 的通过结果代替 move_joint/gripper 的通过结果。
- [ ] 模拟全流程通过后准备独立短期测试权限和具体部署差异；不把所有管理员或整个旧设备凭据直接改成无限制 full，不赋予相机身份执行权限。
- [ ] 检查旧裸 WebSocket、CLI、语音和后台不能绕过本机仲裁；第二管理员正常登录不抢控制权，接管只有停止确认后才可授予新控制权。

**测试：** `robot-remote-service.test.js`、`robot-control-policy.test.js`、`read-only-device.test.js`、`device-runtime.test.js`、`control-leases.test.js`、`takeovers.test.js`；新增 `hardware-acceptance.test.js`。必须同时覆盖只读兼容和受限运动，不删除原有拒绝用例。

**通过条件：** 运动是通过真实证据获得的有限能力；失去任何必要条件都会拒绝新运动并按经实测的策略停止。

## 任务 6：实时反馈、历史入库和网页控制状态

**Files:** 修改 `services/edge-agent/src/thirdhand_edge/{capture,upload,runtime}.py`、云端设备中继/受保护流路由、`apps/web/public/js/admin-control.js`；如需新流，固定为 `/stream/v1/device-state`，在具体部署审阅中列出；历史查询/CSV 保持现有语义。

**Interfaces:** `LiveRobotState={deviceId,bootId,executorEpoch,sequence,capturedAt,stateAgeMs,sourceMode,jointsDeg[6],velocities,moving,sdkConnected}`。实时状态携带源证据并经当前设备认证通道送达；页面分别显示 live state 与 latest stored state，不能把历史查询换个标签叫实时。

- [ ] 先复现 13–16 秒历史上传延迟，区分采集频率、封批、串行上传、TLS、DB 提交和重试等待；基于根因修改，不通过原始数据降采样解决。
- [ ] 反馈流与历史 outbox 分离；新消息有大小/频率边界与会话鉴权，停止与续期优先，不等待历史补传。对后台标签页、断线、过期和错误 executor 补失败测试。
- [ ] 网页显示实际连接、控制权、六轴/夹爪反馈、数据年龄和停止结果；无新鲜反馈时禁用发送。按钮区分模型与真机；不支持的真机功能保持禁用。
- [ ] 验收每条实际命令的操作者、请求/实际目标、开始结束时间、结果、关联样本和错误均可追溯，管理员可查看并导出，观察员可读运行记录但仍不能访问成员目录或发命令。

**通过条件：** 真机界面使用新鲜状态判断，数据库保存完整原始记录且积压可观测；上传延迟有修复前后同口径测量，不能以最终清空积压代替实时验收。

## 任务 7：分批部署与现场运动验收

**Files:** 具体配置/哈希/备份写入 C3c 部署审阅；实测轨迹与故障结果写入 `docs/acceptance/remote-motion-session.md`，敏感现场证据保存在忽略目录。

- [ ] 完成 Node 24 模块测试、真实隔离 PostgreSQL 测试和 Python 设备测试；`TEST_DATABASE_URL` 必须指向专用 thirdhand_test 库，`EDGE_TEST_PYTHON` 使用具备所需依赖的解释器；缺配置/跳过不计通过。最终执行 `npm run test:public-access`、`python -m pytest -q tests/python/edge_agent` 及本轮 Robot 桥接专项。
- [ ] 先部署连接/相机/只读反馈修复，复核任务 1 的持续观察及故障恢复；再展示受限运动所需实际配置和回退。经具体差异审阅后，才部署本机与云端运动准入，保留旧只读包与凭据用于回退。
- [ ] 测试当次记录看护/急停条件、夹爪范围、当前姿态、轨迹、速度、单次时长及停止判据；正常管理员登录/MFA，申请唯一控制权后连接 SDK。首先只读核对六轴与夹爪反馈，不自动归零。
- [ ] 先做静止停止验证与单轴小幅校验，再做六轴不超过 2°协同；按实际反馈和停止表现决定下一步，不连续自动跑完整测试。后续各轴总偏移仍限于本次基准 ±20°。
- [ ] 夹爪先单独验收，再按任务 4 的设备能力评估六轴加夹爪联动；若无法严格同时起动，明确报告顺序和时间差，不伪称“七轴同步”。
- [ ] 故障先在无运动/模拟状态复测；真实运动中的断网、进程/SDK 故障等需逐项写明幅度、预期停止与现场措施并单独现场确认，不沿用此前仅相机的 35 秒故障许可。
- [ ] 每步核对命令回执、实际位置/余动和入库数据；结果未知立即终止后续动作、现场处理，不重发。结束显式停止/断开、释放控制权，确认设备静止和记录完整。

**通过条件：** 完成实际小范围外网运动和停止验收，原始数据/网页/CSV 一致；“通过/失败/未测”逐项标记。不能将本轮受限验收写成全部管理员功能或正式生产上线完成。

## 任务 8：回退与交付

- [ ] 失败时先停止接受新命令并撤销测试范围；通过已验证的停止路径及现场急停确认实际设备状态。状态未知时不得直接恢复旧裸控制入口或以重启代替停机确认。
- [ ] 在静止/断开确认后，恢复备份的云端发布、本机独立服务和只读权限；重新生成执行实例/连接，不恢复旧控制权，不回放命令。
- [ ] 数据库变更优先向后兼容、禁用能力即可回退；实际运行记录保留。视频可独立恢复观看，不能因控制回退而误授运动能力。
- [ ] 回填运行手册、实施状态、当前发布和测试证据。按用户后续确认整理 login 的提交/推送/合并，不把实施文档自动当作 Git 发布许可。

## 阶段交付与当前待提供信息

| 阶段 | 交付 | 需要现场持续值守 |
|---|---|---|
| 0–2 | 基线、故障根因、稳定只读连接与可信视频 | 不发运动，设备保持当前条件即可；涉及相机硬件检查再通知 |
| 3–4 | 实际停止证据、限位核对、明确轨迹与夹爪范围 | 需要，尤其停止/保持/驱动失能试验 |
| 5–6 | 受限运动准入、实时反馈与完整入库，本地/模拟回归 | 本地模拟开发不需要；真机连接验证另记录 |
| 7 | 分批部署复核、现场小幅运动与逐步扩大 | 需要，人员在急停旁且每步保持现场可控 |
| 8 | 安全退出、回退能力、报告与 Git 交付 | 退出时需现场确认，代码整理不需要 |

已获得的 J1–J6 20°范围不重复询问。实际运动前还需明确：夹爪 mm/% 测试量，以及真实设备限位、坐标和停止/保持能力的来源；这些可先从现场 SDK/设备资料核对，无法确定时再由用户或现场人员补充。

本次只编写实施计划，没有修改业务代码、服务器配置或执行硬件动作。首项实施应为任务 0–1 的基线与诊断，不直接切换 full 模式。
