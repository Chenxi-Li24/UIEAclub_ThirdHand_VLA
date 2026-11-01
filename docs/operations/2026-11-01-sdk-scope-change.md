# SDK 权限部署与现场验收记录

用户已批准固定部署及状态验收，初始化允许使能电机和默认闭爪，后续运动保持 readOnly 门禁。

2026-11-01 17:56–17:58（Asia/Shanghai）应用成功：Ubuntu8文件/两个服务配置、云端11文件/迁移012。应用前真实 Robot /health 报 connected=false、moving=false、无固定TCP动作，context 报 readOnly=true、recordingHealthy=true；云端活动租约及在途命令均为0。两服务停止后设备应用器校验新鲜证明和CAN协作锁成功，未打开SDK。

云端发布 `0735390c57d2ad7d`，迁移应用成功；原发布和配置摘要留存，原设备快照保留。设备服务从 agent-sdk-ab786c269838e18c 和 robot-sdk-2fe4b77d3974d3c3 启动，无自动连接，NeedDaemonReload=no。实际 SDK 尚未连续验收。

应用前修正迁移与独立租约准入锁的自阻塞问题，提交 c807176：迁移同一事务锁表、核验空闲、升级锁；完成后另取准入锁切换服务。21项部署测试及独立真实PostgreSQL锁验证通过。应用器现场名 apply_sdk_scope_cloud_v2.py，摘要见部署审阅。

Observer实际签名租约已确认 scope=sdk，真实工作进程多次记录 remote_lease_renew active=true；随后释放原因 renewal_unconfirmed。没有因此关闭超时保护或放宽安全阈值。视频健康标记false，运动不开放。

连接确认发现原生confirm会阻塞浏览器心跳，改为页面内确认（952f746）。确认前不发送连接，取消/失去租约/页面销毁不初始化，7项前端测试通过。固定单文件补丁：

- 原清单0735390c57d2ad7d58d663818c191beb6ad8ab30183f7feeb5cd137e58c318d1。
- 新清单dc458eb35ed369a1a8716b69bb4bd56b7d6b804383e74a6e944da1f68b8fa381。
- 包b8ba140ad28e82f7f7a92fbb5e835c2dcf298b5058aa65b4aa76e224956541c5。
- 应用器c16f33d2dce17c7e13858c7a2abb52e18fe18435fe5089261cc491810524a83f。
- 仅apps/web/public/js/admin-control.js改变，保留4656件，无数据库/Ubuntu/端口/权限变更。5项固定包边界测试通过。沿用版本备份、零租约准入锁、重启业务API和回退流程。

以上单文件补丁为已批准SDK接入验收中的缺陷修复，不扩展权限或硬件动作范围。实际补丁应用和后续验收结果继续追加，不能以模拟测试记为真实10分钟通过。

## 本轮现场核验结果

单文件确认框补丁已应用：云端当前发布 dc458eb35ed369a1，应用记录 applied=true，thirdhand-stage.service 为 active。没有数据库、端口、设备服务或权限范围的附加变更。

18:34 与 18:40 的 Observer 授权均进入设备端；18:40:13.537 记录 remote_lease_arm active=true，18:40:13.702 记录 remote_lease_renew active=true，18:40:14.228 因 browser_stale 撤销。与较早的 renewal_unconfirmed 区分：最新失败明确是浏览器心跳超时。验收 Edge 窗口被系统报告为 minimized；这是待排除的环境因素，尚不能把全部中断归因于窗口状态或校园网。

18:40 后只读核验：sdkConnected=false、readOnly=true、recordingHealthy=true、videoHealthy=false、controlAccepted=true。未执行 SDK 初始化或后续运动；10分钟真实关节/夹爪数据验收未完成。不能把页面出现“真实硬件”来源标签或历史连接事件算作实际关节数据通过。

用户报告的登录无转圈尚未复现。内置浏览器当前登录表单为空，DOM 中存在 auth-spinner；公网脚本及样式含等待组件，Cache-Control 为 no-store。认证及SDK界面16项自动化测试通过（包含延迟请求禁用按钮、转圈、重复提交阻止、超时恢复和非阻塞确认），这些是测试环境结果，不替代用户登录实测。待用户在发生问题的页面提交一次并保留现场检查。

截图保存在本地运行证据目录 .superpowers/sdd/2026-11-01-sdk-source-audit/，不纳入源码提交。部署回退仍使用上文固定应用器记录和原发布；不回滚迁移012已有数据。

CI 核验：部署锁修复 c807176 的运行 41295343458、固定确认框补丁 fea5b2e 的运行 41297298966 均 completed successfully。

## SDK 心跳前端修正（19时后）

用户反馈连接仍立即断开，继续在原只读范围排查。发现前端仅接受最后一次已发送 response 的 fresh ACK；两个有效挑战在网络合并返回时，较早确认被误判为协议错误。改为只接受单调递增、确实发送且本地年龄小于500ms的确认；确认到达不重置其发送时间，不放宽服务器500ms或设备1000ms门禁。重复、未知、过期确认仍关闭通道，不自动重连或重试初始化。

授权HTTP结果返回后再次核对连接绑定和新鲜度，不能在通道已断开时恢复按钮。设备只读能力提示不再遮盖授权失效，按钮按租约实际状态禁用。无数据库、Ubuntu、权限或端口变化；部署目标仅 admin-control.js，候选摘要与现场结果随后追加。Node客户端、UI、真实回环WebSocket共16项测试通过。登录反馈本轮由用户说明在Edge已不再复现，暂不继续修改登录文件。

固定单文件心跳补丁：source c6000ea9907c1ae7e1cef42f56c71305debe5c26，old dc458eb35ed369a1a8716b69bb4bd56b7d6b804383e74a6e944da1f68b8fa381，new 3d3acd1d9fa353a0dcfb66db18f3e373526de73b6da1ae1694b86aa5fe5c3e0c，package b95a8889386c3b3a54e57ec21601b5d98ea90d368eee83bcbe5ee985209799a2，installer 133f6c14cbcd1967e12005658af34e8ae6dbce9c6dcba628d61329c5a7239558。保持其余4656件资源，9项发布边界测试通过；部署沿用零租约/零在途命令准入、备份和回退，只有业务API重启。


心跳单文件补丁经用户追加批准后已部署为3d3acd1d9fa353a0，CI #47（41301269331）通过。现场续期65次后仍因设备lease_expired/云端renewal_unconfirmed中断；未产生新connect命令，未通过10分钟SDK验收。Ubuntu wlp7s0开启节电，TCP存在重传，60次非鉴权HTTPS响应测量最大2.86秒。下一步仅准备了15分钟自动恢复的Wi-Fi节电对照方案，尚未改变设置，见2026-11-01-sdk-wifi-ab-review.md。
