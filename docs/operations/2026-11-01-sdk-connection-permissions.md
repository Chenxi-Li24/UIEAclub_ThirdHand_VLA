# SDK 连接与运动权限拆分

状态：本地实现和测试完成，尚未部署。用户最新要求取代原“观察员不能连接 SDK”：已注册、验证邮箱且会话有效的非管理员也可连接；普通初始化允许电机使能和默认夹爪闭合。初始化之外的运动只允许管理员模式并通过 MFA 和现有安全门禁。

## 权限与界面

| 操作 | Observer 会话 | Administrator + MFA 会话 |
|---|---|---|
| 查看真实状态、模型及历史 | 允许，沿用原数据权限 | 允许 |
| 申请设备连接租约 | 允许，仅 sdk scope | 允许，control scope |
| 显式连接 SDK | 允许；确认初始化使能/闭爪提示后执行 | 同左 |
| 断开自己持有的连接 | 允许 | 允许 |
| 关节、夹爪开合、预设运动 | 拒绝 | 仍需设备就绪、控制租约和安全门禁 |
| 抢占或停止别人的连接 | 拒绝 | 沿用现有确认、停止证据和接管流程 |

管理员账号以 Observer 模式登录时也只有 sdk scope。匿名、未验证邮箱、停用或过期/撤销会话不能连接。只打开设备页不会构造 SDK；连接操作前显示初始化副作用。现场保持单设备单租约，观察员可多端查看，但不能同时建立多个控制器实例。

此处“仅连接”不是无副作用的被动采集：SDK 的 enable_all 和条件 closeGripper 被明确允许。后续独立 gripper 命令不因此开放。自动失联保护及拥有者主动断开仍属于既有设备生命周期处理，不等于开放任意运动接口。

## 实现与协议

1. `platform/identity/src/policy.js` 将 sdk.connect/disconnect 放入已认证观察权限；control.request/command/stop 保持管理员限制。
2. `control-channel.js`、`websocket.js` 允许观察会话建立现有 cookie/同源/CSRF 绑定的控制通道；浏览器连接身份仍由服务端读取。
3. `routes/control.js`、`control/leases.js` 按 opcode 重新鉴权。租约 scope 由服务器的真实角色/模式计算，不接受请求参数授权。connect/disconnect 之外继续要求 control.command。
4. `platform/storage/src/leases.js` 在事务内重新检查真实数据库用户、会话、角色版本、邮箱、MFA、到期及撤销状态。命令必须绑定自己的会话、浏览器和租约；sdk 租约不写入任何运动指令。
5. 签名 lease_grant/lease_renew 带 scope。Ubuntu `services/robot/src/control-policy.js` 保存 scope 并在桥接层前拦截运动；续租不能改变 scope，命令字段不能覆盖。云端要求 sdk scope 的明确 ACK，旧设备不确认时拒绝授权，不下发 connect。
   续查完整链路补齐三处兼容：Python `lease.py` 仅允许可选 sdk/control 字段，`bound_transport.py` 仅回传有效 active scope；云端 `services/device-relay/src/server.js` 对对应 ACK 做相同枚举限制。旧版不带 scope 的管理员协议兼容保留，未知字段与 scope 值仍拒绝。
6. `admin-control.js` 展示共同的 SDK 连接区，观察员无接管/Software stop 按钮；自身释放使用 disconnect。保留双布局、中英文和现有共享状态读取。

沿用现有设备、租约、命令 HTTP 路由与 WebSocket，不新开公网端口。历史记录和事件入库沿用原链路。scope 只存在签名租约及数据库，不将用户凭据发往 Ubuntu。

## 数据库、部署和回退

- 新迁移 `012-sdk-connection-scope.sql` 给 `ops.control_leases` 加 `scope text NOT NULL DEFAULT 'control'`，限制 sdk/control；旧管理员租约保留原语义。服务重启不从数据库恢复活动租约。
- 无新运行依赖、资源或配置字段。沿用现有 Node24、PostgreSQL17、Python3.11 设备环境及启动入口；本地先在隔离库运行现有 migrate 工具，再启动业务服务。不要在开发时复用生产数据库。
- 实际部署必须停止发放新租约、核对零在途命令及真实设备状态，完成备份与迁移，先更新 Ubuntu 签名策略，再上线云端和网页；两端固定候选需包含 C8 尚未部署的实际路径修正及最新状态上报文件，不能直接套用旧 C8 三文件包。
- 回退先关闭新授权、结束本次租约并取得既有停止/断开证据，再回退云端和设备固定版本；保留 scope 列和审计数据。旧 API 仍拒绝观察员操作，不删除真实记录。
- 本文是已实现功能说明，不是固定部署包或服务器变更批准。当前 staging 仍是旧权限；C8 修正版尚未获准应用。

## 验证

完整 public_access 套件 337/337 通过（隔离 PostgreSQL、Node24、Python3.11）。之后新增的真实 HTTP/WebSocket 鉴权用例与其余三个 scope 用例一起 4/4 通过。测试验证观察会话能够签名申请并连接、续租、断开；移动、夹爪、回零、抢占、停止别人、借用管理员租约、伪造管理员角色、篡改 scope 均拒绝；旧设备无 scope ACK 时不发送命令。

Robot 策略测试验证 sdk scope 在设备侧拒绝运动和续租提权。前端测试验证观察员可用连接入口但无运动权限，挂载不自动建连接。本轮数据库与网络测试使用模拟设备，绝非真实机械臂运动或十分钟实测验收。未连接现场 SDK，未改变 Ubuntu/CAN/相机服务。管理员真实运动与通信中断停止效果仍未完成现场验收。

后续完整链路核验修复后，public_access 340/340 通过；其中三个真实 Python 子进程 + TLS 中继用例覆盖 legacy/control/sdk 的授权、续租与 scope ACK，拒绝未知枚举和额外字段、不外泄非白名单诊断，命令重放只调用一次模拟 Robot。它们发现并防止“云端模拟设备通过而实际 Python 网关拒绝 scope”的兼容遗漏。

Python 网关88项及固定部署边界20项均通过。云端11文件（含迁移012）、Ubuntu8文件及两个服务入口配置已经固化；两端默认只读预检通过，尚未激活。构建来源、准确摘要、应用顺序、回退及真实验收边界见 [SDK固定部署审阅](2026-11-01-sdk-scope-deployment-review.md)。
