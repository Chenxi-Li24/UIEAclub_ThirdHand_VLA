# SDK 权限与实时状态：固定部署审阅

状态：2026-11-01，代码和固定包完成；服务器仅上传至独立准备目录并执行默认只读预检，尚未激活。本文替代未应用的 C8 修正版候选，保留已上线登录等待反馈。

## 结果与边界

已验证邮箱、有效登录的观察员可以主动连接 SDK，连接前明确提示初始化使能电机以及默认夹爪闭合。sdk 租约只允许连接、续租和断开自己的连接；后续关节、夹爪开合、预设动作、接管和停止他人的连接不会因此开放。管理员账号在 Observer 模式下也只有这一权限。

后续运动要求管理员角色、Administrator 模式、MFA、control 租约以及原安全门禁。此次保留现场 readOnly=true；部署不等于开放管理员实际运动。通信中断停止的现场验证仍需另行完成。本次验收不发送关节或独立夹爪运动命令。

沿用现有鉴权、CSRF、签名、mTLS、单设备单租约和失联保护。同步补上 C8 的实际运行路径和独立最新状态上传；历史记录上传、相机发布器、SDK 库与原控制器不替换。

## 固定内容

新权限与协议来源提交 `3512410788da5e4e2878137e4ddd7e172e5bcdd4`；设备状态补丁沿用固定 C8 源码 `7e65b5d3b59fb7359dec1262d1f7a31c9a63139d`。构建只读 Git 固定版本，不读取其他任务的工作区修改。

| 项目 | 固定值 |
|---|---|
| 云端当前版本 | dfbca02d47ca7f40 |
| 云端当前清单 SHA256 | dfbca02d47ca7f4020354567482265c5f2645a76e509a3f82cf4d23641d5aa4e |
| 云端新版本 | 0735390c57d2ad7d |
| 云端新清单 SHA256 | 0735390c57d2ad7d58d663818c191beb6ad8ab30183f7feeb5cd137e58c318d1 |
| cloud.delta.json.gz SHA256 | 58a30ba9d6d07b4b11503f5fee8875bfc5c4af56d97e341b0dba074b72725fe5 |
| 云端应用器 SHA256 | 452c53328c00626aebc159742e601ad00b7e2e21dd05ce661b0b3ca5658c4a0a |
| device.delta.json.gz SHA256 | 5358aa5f57f7efd09ed67c29e6e1bfe8433fc8af20059c05f441012b8ca9f1a1 |
| 设备原始基线 pins SHA256 | 4fb5c07b369451cb95636ab2a73680873b2adf78ca9ce530e6327718f976907b |
| 设备应用器 SHA256 | cbd1713dbc93303f4c41b0c1f2f4a3248bc2cd8f00b1d504510083419fb8292b |

云端更改 10 文件、新增 1 文件，保留 4646 个现有文件，共 4657 件：

- `apps/web/public/js/{admin-control,device-state,i18n-cloud-catalog}.js`
- `platform/identity/src/policy.js`、`platform/storage/src/leases.js`
- `platform/storage/migrations/012-sdk-connection-scope.sql`
- `services/cloud-api/src/control/{control-channel,leases,websocket}.js`
- `services/cloud-api/src/routes/control.js`、`services/device-relay/src/server.js`

数据库迁移012只为 `ops.control_leases` 增加 sdk/control 枚举约束的 scope 列，旧数据默认 control；不增加数据库账号或 SQL 授权。迁移事务持有标准迁移锁，并校验固定摘要 `331371c9b0bf0d1cfcb0a862134213428a64b4b9285a7c906d660a65752965ed`。回退保留列与数据。

Ubuntu 从实际运行的 agent-source-aef304c8c1efc5de / robot-6a801e6404e6265e 派生独立快照，修改 6 件、新增 2 件，保留其他 52 件：

- Agent：runtime.py、telemetry.py、latest_state.py、state_upload.py、lease.py、bound_transport.py。
- Robot：remote-gateway.js、control-policy.js。
- 新目录：`~/.local/share/thirdhand-stage-device/20261031/agent-sdk-ab786c269838e18c`、`robot-sdk-2fe4b77d3974d3c3`。
- 两个现有用户服务分别增加 `zzz-sdk-scope-state.conf`，仅切换 PYTHONPATH / ExecStart 到新快照；原配置和源码保留。

无新公网端口、证书、Nginx 变更、运行依赖或展示站改动。重启云端 thirdhand-stage.service 和 Ubuntu 的 thirdhand-tcp-calibration-robot.service、thirdhand-stage-edge-read-only.service；视频鉴权可能短暂重连。

## 应用顺序和回退

1. 在应用前重新核对线上清单、文件、服务路径、零活动租约与零在途命令；读取设备实际状态，证明 SDK 断开、无运动。状态缺失或不满足就停止，不把断开连接推断为物理停止。
2. 保存原发布和配置不变量、数据库 scope 迁移前结构收据；原数据库内容不导出到聊天。这里的结构收据不是完整数据库备份，沿用既有数据库备份机制。
3. 停止 edge 后停止 Robot；用真实核验结果生成不超过 60 秒的私有 clearance，执行设备应用器。应用器再次核对两服务停止、源文件与配置摘要及 CAN 协作锁，只写新快照和两个固定 drop-in，不自行启动服务。
4. 云端应用器取得安装锁，先在同一数据库事务中锁定租约表、复核零活动租约/在途命令并应用迁移012；然后取得独立租约准入锁，再次复核空闲，校验全部文件、切换固定发布并只重启业务 API。加列兼容旧版本。不能在另一连接持有 SHARE 锁时执行 ALTER TABLE，否则会自行阻塞；也不能先启动新网关配旧云端，因为旧中继会拒绝 scope ACK。
5. Ubuntu daemon-reload，先启动 Robot，验证未自动连接 SDK，再启动 edge；核对有效路径、状态进程、历史上传与原保护。检查云端健康、页面资源、真实/模拟状态隔离。
6. 使用有效登录会话，由页面显式连接 SDK，允许用户已批准的初始化使能和闭爪，进行 10 分钟只读反馈验收，结束后断开。确认观察员的后续运动被拒绝；拒绝路径先用隔离测试验证，不向真机发送试探性运动。管理员实际运动本轮保持门禁关闭。
7. 任一步异常停止切换。云端按固定应用器回退原发布，保留 scope 列和审计数据；设备需新鲜停止证据、停止两服务后移除本次两个摘要匹配的 drop-in，再恢复原入口。保留原/新快照，不递归删除现场目录。

准备目录为云端 `/var/backups/thirdhand/access-sdk-scope-20261101`、Ubuntu `~/.local/share/thirdhand-stage-device/SDK-scope-state-20261101`。默认执行应用器只审阅；`--apply` 才修改运行入口。应用前如发现其他任务切换版本或修改配置，重新生成候选，不覆盖。

## 验证与未完成

- 本地 public_access 340/340 通过，隔离 PostgreSQL、Node24、Python3.11。
- Python edge_agent 88/88 通过；云端/设备固定部署边界测试 20/20 通过。
- 三种 legacy/control/sdk 协议经过真实 Python 子进程和 TLS 中继测试；验证严格字段、有效 scope ACK、续租不提权、重放只调用一次模拟 Robot。
- 权限测试覆盖观察员连接/断开、运动拒绝、角色伪造、借用租约、旧设备不确认 scope 时拒绝下发。测试设备为模拟 Robot，不能记为物理验收。
- Ubuntu 已通过实际路径及默认只读预检，尚未激活。云端默认预检同样通过：applied=false、11件固定内容、迁移012尚未应用（checksum=null、columns=0）、sdkActions=0、motionCommands=0；上传包和应用器 SHA256 均匹配上表。CI 结果以本次最终提交对应运行记录为准。
- 未完成：实际部署、真实 SDK 10 分钟连续反馈、断线恢复及现场运动停止验收。无需重新提供 SDK 链接；初始化副作用已确认并获用户允许。

需要最终具体部署确认的依据：已批准 [C8部署审阅](2026-11-01-C8-deployment-review.md) 明确“实际服务器变更须审阅固定候选后应用”。此次固定内容增加迁移012、观察员连接权限和实际服务路径配置，超出此前只批准的三文件登录修复。

用户已批准本组部署与状态验收。应用前复查修正应用器内部锁顺序，现场准备目录另存为 `apply_sdk_scope_cloud_v2.py`；业务包、设备包、迁移内容、服务范围不变。部署边界测试现21项通过，另在本地独立 PostgreSQL 库实测活动租约拒绝、同事务锁升级和准入锁持有期间重复迁移检查，均通过。原 b01cc19 两项CI均成功；本次锁修正有独立提交。
