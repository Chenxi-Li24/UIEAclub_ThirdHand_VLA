# C8 部署与验收记录

2026-11-01。本轮获得固定部署与只读验收授权，但 **C8 尚未全部完成**。云端与路由已部署，设备候选回退；本轮没有发出 SDK connect、关节、夹爪、回零或运动指令。管理员由用户本人登录后进行页面验收。

## 云端已部署

- current 从 `1fdfb95e8d905105` 切换至 `4688a5dfdcf76810`，26 件固定源码，完整清单 4656 件。使用审批包 cloud-candidate-v3，旧 release 和备份保留。
- 新 manifest SHA256：`4688a5dfdcf768109296765b7937fd8bbb47ec22bd27ae4b25a11562590da1f8`。
- cloud review/apply 记录保存在 `/var/backups/thirdhand/access-C8a-ui-sdk-20261101/`。API 和 Nginx 均 active；私有 `http://127.0.0.1:3202/healthz` 返回 `deviceControl=explicit-read-only`。公网 `/healthz` 返回404，不把该未公开路径当作业务故障。
- Nginx `/edge/v1/state` 已添加。配置 SHA256 为 `0b65801a9933e1ad1e3b7f4dbaa69b94b63d9e72032e7ae094b5214e6ed32c68`；无客户端证书请求得到400、`No required SSL certificate was sent`，严格 mTLS 仍有效。
- 路由备份与结果在 `/var/backups/thirdhand/access-C8b-state-route-20261101/`。没有端口、数据库、账号权限或相机证书变更。

## Ubuntu 部署目标错误及回退

原预检只核对了旧目录文件摘要，遗漏了服务实际加载路径。这是本次部署准备缺陷，不能归因于用户或现场改动。

审批包曾向未使用的 `20261031/agent-source/` 和 `20261031/robot/` 安装5文件，并重启两个既有服务。后续发现控制心跳超时及 NRestarts=4，按回退流程恢复了这5文件并重启原服务。运行服务实际并未加载上述新文件，因此不能把网络超时直接归因于 C8 状态发布代码。

实际生效路径经 `/proc` 中白名单字段及 systemd 路径核对：

| 服务 | 实际源码目录 |
|---|---|
| thirdhand-stage-edge-read-only.service | `20261031/agent-source-aef304c8c1efc5de` |
| thirdhand-tcp-calibration-robot.service | `20261031/robot-6a801e6404e6265e` |

它们分别来自 C3c 传输修复和 C3e 软件失联保护。13:32:56（北京时间）恢复后，后续只读检查两服务均 active、NRestarts=0、NeedDaemonReload=no；这只是复查时的结果，不是30分钟网络稳定性验收。已读取的 context 为 SDK=false、readOnly=true、recordingHealthy=true。

原设备候选 SHA256 `12ac8cf0773393aa4c36e6792f4944e617420b58afb7730b500cd8f06918815d` 已停用。仓库 `apply_ui_sdk_device.py` 对默认审阅与 apply 明确拒绝，保留恢复原备份的 rollback。服务器旧安装器虽仍保留，也不得再次 apply。

已重新核对实际目录21件 Agent、36件 Robot 公开源码/清单及7份 unit/drop-in 摘要；没有输出私有配置或凭据。针对实际基线生成的本地5文件差异包为22736字节、SHA256 `7ad32168a0cd066b31e2cdcb22a7700ff57d76c5a83d5ef32b66f84aaa3ed00c`。原 upload.py、robot-controller.js、startouch_bridge.py 不变。该包只是复核差异，**不是已批准安装包**，尚无完整快照激活与回退验收，不能直接在版本目录内覆盖。下一候选应派生新的源码快照，固定实际 unit 路径及完整基线，保留现有版本供回退。

## 线上页面验收

| 检查 | 实际结果 |
|---|---|
| 管理员会话、个人资料 | 可进入、可读取 |
| 安全与登录分组 | 已绑定验证器；没有常驻密码框；未更改认证设置 |
| 成员与权限 | 自动显示注册用户与管理员申请；CSV入口保留；没有修改成员权限 |
| 数据入口 | 正常进入 history；自动显示50条已存硬件采样；日期/时间分框；本地时区显示正确 |
| 实时设备状态 | 网关在线但没有最新实测样本，关节/夹爪显示未提供；不能当作SDK已连接 |
| 相机 | 目录可加载；观看请求最终失败，video readyState=0、尺寸0×0；未通过视频验收 |
| 两套布局/语言/角色矩阵 | 前次本地24组合及教程测试保留；本次线上仅实际管理员、中文、新工作台局部验收，不冒充全矩阵线上通过 |

历史页显示10月31日已有 hardware 采样，**不是本轮实时反馈**。本轮未执行导出任务或下载成员私有数据；只检查入口与已显示记录。

发现连接请求结束后前端可能永久停留“正在连接”。本地补丁：使用独立 attempt 标识；成功或失败均结束 pending 并重新读取实测反馈；旧请求不能清除后发请求；超过15秒不再显示正在连接。请求结果不用于捏造已连接、已断开或已停止状态，仍由真实反馈决定。补齐 `Unknown` 中文翻译。**这些后续补丁尚未部署到云端**。

本轮新增相关测试：Node13/13（包含实际按钮成功/失败的异步状态收尾、过期、重叠请求和观察员拒绝），Python设备安装器6/6（停用后拒绝 apply，仍能回退）。第一次Python测试因沙箱临时目录无法创建而未执行测试；改为工作区专用临时目录后通过。没有因此修改服务运行代码。

## SDK 只读验收的前置阻塞

本地及 Ubuntu 的 SDK 目录只找到 ArmController 构造函数声明/封装，未找到 `ArmController::ArmController` 原生实现。无法据此证明初始化不使能、不回零、不运动。已向用户请求对应 SDK 版本的完整源码、初始化说明或厂商确认。未通过初始化核验前，不执行已批准但带前置条件的10分钟真实连接测试。

这不表示 SDK 一定有动作副作用；表示当前证据不足。历史成功连接记录也不能代替构造函数副作用检查。

## 剩余执行顺序

1. 完成实际运行快照的固定设备候选、激活器、路径一致性保护及回退测试；将本地 pending/UI 修复一并形成固定云端增量。按已批准审阅中“源码/current/配置变化则停止”的要求，具体修正版范围完成后再申请实际应用，不直接套用旧审批包。
2. 独立核对相机观看失败的请求/发布链路，恢复真实解码画面后再做稳定性及既定故障复测，不把空画面当作安全撤销通过。
3. SDK初始化证据通过后，由管理员显式连接，完成10分钟只读字段/单位/时间戳/过期/恢复对照；网络不稳定应如实记录，禁止自动重试运动。
4. 补齐线上两布局、两角色、双语及窄屏复核；正式教程provider仍由队友接口合并时接入，保留现有进度。

本地证据目录 `.superpowers/sdd/2026-11-01-ui-sdk-audit/`：`C8-cloud-health-mtls.png`、`C8-staging-account-security.png`、`C8-staging-history.png`、`C8-staging-camera-failed.png`、`ubuntu-active-inventory.json`、`active-device-diff-review/`。证据和私有运行结果不提交Git。其他任务的XVisio/C++/相机Python未提交改动保留，未纳入本次提交。
