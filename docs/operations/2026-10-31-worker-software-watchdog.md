# Ubuntu 进程内失联取消：本地候选与验证边界

状态：仅本地实现和离线验证，**未部署到 Ubuntu，未连接真实 SDK/CAN，也未执行真机运动**。主任务负责 policy/gateway 集成和具体部署审阅。本候选不能证明机械臂物理停止或失能。

## 已核验的 SDK 边界

当前仓库 SDK 的公开 `interfaces_0825fasttest.hpp` 和 `pybind_0825testfast.cpp` 暴露 `cleanup()`、关节/轨迹/夹爪命令和状态读取；未发现专用的受控停止、取消后继续读取新鲜反馈、原生通信失联急停接口。控制循环实现只有预编译 `.so`，不能依据符号或方法名推断内部停止行为。

`README_API.md` 的 Interrupt Handling 说明 blocking waypoint/MotionProgram 可由 cleanup/退出中断，但 cleanup 用于退出处理，不能替代硬件急停。`move_joint_waypoints`、`move_l`、`run_motion_program` 和 `cleanup` 绑定使用 `gil_scoped_release`，桥的运动线程在调用这些方法前已释放 Python `arm_lock`，所以正常可调度时另一个 Python 线程能请求取消。SDK 构造和若干 getter 没有该 GIL 释放声明，SDK 内部锁也未见源码；若它们长期占住 GIL，监控线程无法保证及时执行。

夹爪公开接口没有独立反馈时间戳、速度或驱动失能确认。当前配置里的 gripper watchdog 不能作为已启用/已实测的通信失联保护。本候选不修改任何关节/夹爪配置、速度、限位、看门狗参数或 CAN 帧。

## 三层软件路径

1. Node `LeaseWatchdog` 除 gateway 的周期检查外，独立设置单调时钟定时器；TTL 不超过1000 ms，可传入 `renew(ttlMs, {deadline})` 的已计算单调绝对上限，排队或调度延迟不能重新获得完整 TTL。过期或 clear 后同一代终止，只有可信调用方显式 reset 到更高 leaseEpoch 才能重新启用。
2. `StartouchBridge` 只有收到匹配的新 worker 能力握手后才能发送租约，环境 `STARTOUCH_REMOTE_LEASE_GUARD=1` 才启用远程模式。`armRemoteLease`、`renewRemoteLease` 和 `revokeRemoteLease` 保留原 issuedAt/expiresAt，不把排队的旧心跳改成新的相对时长。stdin 背压时拒绝继续排心跳。返回 true 只表示已写入 worker 管道，不是 worker ACK，更不是物理停止确认。
3. Python `RemoteLeaseGuard` 在独立线程检查本地单调 deadline，通常每20 ms检查一次。独立 stdin reader 优先处理租约控制消息，避免 main 正在 SDK connect/稳定采样时把续期阻塞在普通 SDK 命令后。首次换算先采 mono 再采 wall；续期对首次锚点与当前观测取更早上限，墙钟回退不能延长授权。每次 wall 读取后和续期提交前重新采 mono，并检查**旧** lease deadline 仍有效；wall 读取时暂停不能复活到期租约。poll 与持续初始化都采用当前 UTC expiry 和单调 deadline 中更早的期限，UTC 前跳跨期限立即失效。过期/撤销先锁死 admission，再在 guard 锁外取消队列、follow、夹爪目标并调用既有 SDK disconnect/cleanup。

这三层依然是软件保护。1000 ms 是租约期限上限，20 ms 是软件轮询间隔，不是操作系统实时调度或真实机械停止的最大时间保证。Python worker 整体死亡、Node 和 worker 同时死亡、SDK 占住 GIL、主机/操作系统挂死或断电均未获得独立硬件保护证明。

## 原执行绑定和初始化竞争

租约绑定 device/boot/executor/connection/certificate、硬件指纹、leaseId/leaseEpoch；sequence 严格增加。JS 给每个远程 SDK 命令附加捕获时的原租约。Python 在接收、进入运动队列和真正调用 SDK 前复核，旧队列不能借新 epoch 恢复执行。默认本地 UI 模式仍保持原行为；启用远程 guard 后不允许绕过 worker lease 直接 connect/运动/follow/夹爪。

连接在首次开始时必须具有有效原租约。SDK 构造和稳定采样可以持续超过首个短租约，但只能由**同一完整绑定连续续期**保持有效；新 leaseEpoch 不能救活旧 constructor。连接提交前复核 connection_generation 和原绑定，任何撤销/到期使晚返回构造拒绝提交并 cleanup。构造尚未返回时不能称 SDK 已释放，也不提前释放 CAN 唯一控制锁；待晚构造 cleanup 成功后才释放。若原生构造占住 GIL，实际取消只能在其返回后进行，延迟保持未知。

stdin EOF 会撤销租约并确保 main 的 finally 调用 shutdown。独立 reader 与监控回调的 cleanup 使用同一 disconnect 锁，防止并发取消因暂时看不到 self.arm 而错误宣布资源已释放。

远程模式所有事件通过有界64条非阻塞队列交给独立审计写线程；SDK/guard 线程不等待事件锁或父进程输出管道。取消路径先清空队列、调用 SDK cleanup 并结算状态，再排入取消/连接回执。父进程输出读端关闭或暂停读取导致管道写满时，审计允许丢失，取消不能因记录失败而跳过。此队列不充当可靠存储，也不会编造已送达回执。

## 停止回执与准入

`createSoftwareStopAdapter` 以 commandId、原 executor/hardware 与 lease epoch 关联请求，拒绝同 ID 不同绑定复用；一秒结果预算和最终单调复核拒绝晚到回执。SDK cleanup 成功只标记 `sdkReleased`；默认结果仍是 `state=unknown`、`CONTROLLED_STOP_UNSUPPORTED`、`depowered=false`。

只有可信本地配置明确提供经过核验的原生 stop callable、停止 profile 和新的硬件反馈读取器时，才调用既有 `validateStopEvidence` 验证稳定采样窗口。SDK 返回的布尔 stopped、进程退出、连接断开、单次零速度和缓存夹爪位置均不算反馈。当前 SDK 尚不支持此配置，`controlledStop=false`；实际运动门禁应保持关闭。只读 SDK 释放路径独立处理，不能拿其回执充当物理停止证据。

`remote_lease_status` 与 `remote_lease_expired` 通过 RobotController 透传给 gateway/source audit；本候选不自行改变云端审计/数据库结构。

## 离线证据

精确六件生产文件摘要见本计划 `stop-evidence/worker-watchdog-fixed-pins.json`，替代保留作审阅前历史的 `worker-watchdog-local-pins.json`。它们是 Node watchdog、软件停止适配器、Python guard、两个桥文件和 controller 的两类事件透传；没有媒体或配置改动。独立审阅的两项 P1（wall 读取暂停复活旧期限、审计阻塞阻断实际 cleanup）均已先重现 RED，再在同一修复轮次修正。

- 新 Node 定向测试 **28/28**，包括原 deadline 上限、终止不可续、旧定时器、晚停止反馈、请求/epoch冲突、worker版本错配、背压和审计转发。新增真实模拟 worker 在 Node 通过 Atomics.wait 暂停事件循环1.4秒期间独立到期并完成模拟 SDK cleanup，事件时间早于 Node 恢复回调；它不依赖 Node timer 触发取消。日志 `worker-review-node-final.txt`。
- Python 定向测试 **34/34**，包括纯 guard、初始化竞态、旧队列绑定、独立 stdin 续期、EOF、既有停止语义，以及真实本地子进程的显式 SIMULATE 模式。新增 wall 读取暂停跨旧期限、UTC 前跳，以及实际 os.pipe 读端关闭/写满并带排队动作的取消回归。日志 `worker-review-green.txt`。
- 模拟子进程在 stdin 保持打开、父端不再发送续期或 stop 的情况下，自行到期，取消正在插值的模拟运动并释放模拟 SDK；回执仍保持 physical unknown。此项不导入真实 SDK、不打开 CAN，不代替实际 Ubuntu 失联和真机停止验收。

尝试 Robot Python 广回归得到55通过、3失败和1收集错误：既有测试硬编码 Windows 不可用的 python3、默认 cp936 读 UTF-8、SDK速度 patch 断言不符、缺 PyYAML。日志已移除 pytest 自动打印的进程环境行。它们未被标记通过，也未通过修改无关代码绕过。Node 广测因主任务集成及测试数据库维护而取消，不计为完成结果；主任务集成后统一运行。
