# SDK 续期调度修复固定部署审阅

状态：用户已明确批准上传、部署并继续验收；2026-11-01 22:40（北京时间）已应用。只读前检通过，安装器返回 applied=true、exit=0；当前发布为下列671809219c9cefc8。业务服务active，健康检查仍为explicit-read-only。只改两件固定源码、保留4655件；没有数据库、Ubuntu、网络或权限变更。授权续期实测未通过，结果见文末。

## 本次具体操作

1. 新建云端专用备份目录 /var/backups/thirdhand/access-sdk-renewal-20261101（root 0700），只上传 cloud.delta.json.gz 与 apply_sdk_renewal_cloud.py 两件固定文件，文件仅root可写。
2. 校验文件摘要，默认只读运行应用器，完整核对现有4657件清单、受保护配置、原发布及固定候选；基线不符立即停止。
3. 沿用已有部署锁、零租约/零在途命令准入，记录原发布与受保护配置摘要，复制原发布后替换下列两件源码、切换 current 并仅重启 thirdhand-stage.service。
4. 检查服务健康仍为 explicit-read-only，清单和受保护配置一致。部署本身不初始化SDK；业务API重启会短暂断开网页/设备通道，通道按原规则撤销并重建，用户若有过期会话仍须本人登录。
5. 先做无SDK初始化的观察员授权续期测试并查看受限诊断。若链路达到稳定前置条件，再继续此前已批准的显式SDK初始化与10分钟状态验收。允许原有初始化使能/默认闭爪副作用；不发送任何后续运动、不自动重复连接或重放命令。

## 固定范围

源码提交：6778469f3ee63a801d8b0f16f86e2981330635b1。

| 文件 | 新SHA256 |
|---|---|
| services/cloud-api/src/control/leases.js | b1227b7bdb0884d76d30f78d8e12acc3d2a0bf263dee5f01e204b13e013517f0 |
| services/cloud-api/src/device-runtime.js | d9c6daba0daa2d186f3d9a1d9a2ed734fa74a2a2821978edf82719bf783b2c7a |

- 原发布：/opt/thirdhand-stage/releases/3d3acd1d9fa353a0。
- 原清单：3d3acd1d9fa353a0dcfb66db18f3e373526de73b6da1ae1694b86aa5fe5c3e0c。
- 新发布：/opt/thirdhand-stage/releases/671809219c9cefc8。
- 新清单：671809219c9cefc81997774a77e83dc791f8b725541a76d5da9e663bd4e5f990。
- 包：286197字节，SHA256 c54d27e6e657e4a96b4c6747e4f6fcacd710b7883ce6f9ea9423fe85f75c27cd。
- 应用器：SHA256 4f3e70dc149c8befd7071738c45240e065ef16efefa856e51475bb88e071740b。
- 总文件4657件，改变2件、保留4655件，没有增删源文件。

仅在设备ACK等待期间保留一个待处理浏览器新鲜事件，ACK后再次校验并串行发送续期。增加撤销边界检查；错误日志只含固定阶段、白名单代码和有界耗时。不得输出会话/用户/设备标识、密码、令牌、签名或载荷。没有浏览器新鲜事件则不续期；到期租约不复活。

不改浏览器500ms/设备1000ms期限，不改角色、数据库、Nginx、Ubuntu、设备凭据、网络、端口或展示站；相机任务的其他未提交源码不在包内。原网络重传可能仍触发断开，不能宣称此修复已解决线路问题。

## 验证依据

- 旧实现的延迟ACK场景先失败，修复后新增7项集成测试全部通过。
- 完整公网访问352/352通过，含真实隔离PostgreSQL、WebSocket及Python模拟worker，零跳过。
- 三种固定包边界测试13/13通过，覆盖额外文件/内容篡改/错误摘要拒绝。
- 已只读核对线上 current、清单摘要及两件原源码均符合基线，thirdhand-stage.service 为active。
- CI以最终候选提交关联结果为准，在实际部署前核对，不能用本地测试冒充CI或真机验收。
- 最终候选8e032d6的CI运行41315672136成功；部署后未做新的真机初始化，本轮不把网络样本或模拟worker当作真实SDK10分钟验收。

## 执行与回退

在上述云端目录内，先 python3 apply_sdk_renewal_cloud.py 只读审阅，再在批准后执行 python3 apply_sdk_renewal_cloud.py --apply。安装器复用已固定摘要的既有部署/准入保护，不从网络下载执行脚本。

切换后的失败自动回退；必要时 python3 apply_sdk_renewal_cloud.py --rollback，验证旧清单与备份后恢复旧current，只重启业务API。没有数据库迁移，因此不回滚账户、点位或记录。回退不依赖新包完整性；任何受保护配置或基线漂移都停止，不能覆盖其他任务发布。

本地构建：python tools/deploy/build_sdk_renewal_release.py --baseline .superpowers/sdd/2026-11-01-sdk-source-audit/sdk-heartbeat-candidate/expected-manifest.json --destination <新的空候选目录>。构建从固定Git提交读取，不打包脏工作目录。

## 已执行的现场验收

- 22:42:46.391首次申请，22:42:46.456确认，22:42:47.181释放，数据库续期序号3、原因renewal_unconfirmed。Ubuntu对应arm及前两次renew成功，第三次无worker续期事件。新云端诊断为confirmation / LEASE_UNCONFIRMED / elapsedMs=162，不能把这次快速拒绝直接归因于网络超时。
- 22:49:16.659第二次申请，22:49:16.773释放，未确认、续期序号0、grant_failed。未继续盲目重复申请。
- 两次均为Observer授权链测试，未点击SDK初始化确认。最后connect命令仍是13:34:56.44（北京时间）的历史记录；本轮未新增connect或后续运动。设备sdkConnected=false、readOnly=true。
- 自动审批拒绝拟议的本机HTTP响应载荷抓取，理由为可能包含认证信息；抓取没有执行，后续改用受限应用日志诊断。不得通过其他工具绕过该拒绝。
- SDK十分钟真实状态验收尚未开始。下一步只准备白名单设备拒绝码诊断；不能通过延长超时、放宽权限或用模拟数据宣称修复。

云端应用输出：/var/backups/thirdhand/access-sdk-renewal-20261101/apply-output.json；本地截图证据：.superpowers/sdd/2026-11-01-sdk-source-audit/sdk-renewal-applied.png。备份与回退沿用上述固定应用器。
