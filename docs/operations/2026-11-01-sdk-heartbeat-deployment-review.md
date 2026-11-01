# SDK 心跳修复部署审阅

## 问题与行为

浏览器将较早但仍有效的心跳ACK误判为协议错误；租约HTTP成功响应也可能在通道已断开后重新启用按钮。固定源码提交 c6000ea9907c1ae7e1cef42f56c71305debe5c26 修复这两个问题，并让授权断开提示不被设备只读能力提示覆盖。

只接受单调递增、确实发送、年龄小于500ms的ACK，收到ACK不延长其发送时刻；服务器500ms、设备1000ms门禁不变。无自动重连、无初始化重试。保持观察员可显式连接、后续运动仅管理员且当前readOnly门禁仍开启。

## 具体变更

向宝塔云服务器独立目录 /var/backups/thirdhand/access-sdk-heartbeat-20261101 上传 cloud.delta.json.gz 和 apply_sdk_heartbeat_cloud.py 两件文件；校验摘要、运行默认只读审阅，零活动租约和零在途命令时应用，仅重启 thirdhand-stage.service。

- 只改变 apps/web/public/js/admin-control.js，保留4656件其他文件。
- 当前清单 dc458eb35ed369a1a8716b69bb4bd56b7d6b804383e74a6e944da1f68b8fa381。
- 候选清单 3d3acd1d9fa353a0dcfb66db18f3e373526de73b6da1ae1694b86aa5fe5c3e0c。
- 包摘要 b95a8889386c3b3a54e57ec21601b5d98ea90d368eee83bcbe5ee985209799a2。
- 安装器摘要 133f6c14cbcd1967e12005658af34e8ae6dbce9c6dcba628d61329c5a7239558。
- 不改数据库、Ubuntu服务、账号、权限、端口、相机或展示站。
- 部署自身不连接SDK，不发送运动。之后延续已批准的连接/初始化副作用和10分钟真实状态验收；不放宽任何超时保护。

## 验证与风险

客户端、UI、真实本地回环WebSocket16项测试通过；固定包边界9项通过。迟到ACK、重复ACK、未知ACK、过期ACK、迟到租约及角色边界均有断言。此为测试环境验证，不能替代真实网络和SDK验收。

业务API重启会短暂断开网页/相机授权连接。已备版本锁、清单摘要、只读预检、原版本保留和回退逻辑；若当前发布、文件摘要或活动租约发生变化，停止而不覆盖。

## 回退

在同一备份目录运行 python3 apply_sdk_heartbeat_cloud.py --rollback，恢复旧发布 /opt/thirdhand-stage/releases/dc458eb35ed369a1，保留已有数据库和点位数据。无迁移需要回滚。

## 当前状态

本地候选及测试已完成，源码和部署定义已提交推送至 fork login；服务器仅创建独立空目录。浏览器上传最后一步被自动审批拒绝，理由是这组后续上传尚无明确确认。未绕过该拒绝，未上传或应用本补丁。等待用户对上述两件文件上传和单文件应用的明确批准。


## 批准与应用结果

用户随后明确批准“上传、应用并继续验收”。两件文件上传成功，远端摘要与固定候选一致；默认审阅通过后应用返回applied=true，新发布3d3acd1d9fa353a0，保留其余4656件文件。源码及候选提交bd72e87的CI运行41301269331 completed successfully。

实际Observer会话已复用；DOM确认框正常显示，但后续租约因renewal_unconfirmed撤销，确认框自动取消。19:32:37至19:32:55约18秒期间续期65次，Ubuntu最后续期19:32:54.524，19:32:55.324记录lease_expired。没有新的connect命令下发，10分钟真实数据验收未完成。剩余链路问题与已修复前端ACK问题分别记录，不能宣称SDK已恢复正常。

公网未登录请求admin-control.js返回401（该工作台资源受鉴权），未绕过鉴权取资源；部署应用器已核对完整清单，登录后的页面显示新的失效提示。运行证据为sdk-heartbeat-applied.png和sdk-heartbeat-state.png，位于本地未跟踪的证据目录。
