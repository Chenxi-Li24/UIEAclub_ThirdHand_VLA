# SDK 有界续期发送修复部署审阅

状态：用户批准后已上传并部署，当前线上为805921eeb03285b8。本地完整公网访问364/364、固定包边界21/21及最终候选cdf9c84的CI通过。部署后的两次真实授权仍到期；未初始化SDK，真实十分钟状态验收未通过。以下固定清单保留为本次执行依据，实际记录见末节。

## 为什么需要这组修复

09:38现场授权经9次续期后，设备先到期，迟到续期被拒绝。旧实现等待设备上一ACK才发送下一次续期，在返回链路延迟时额外消耗下行有效时间。新实现仍串行检查身份、数据库、设备注册并按顺序发送，但允许最多4条签名续期等待确认，满额仅保留一个最新浏览器事件。没有新事件不续期；任一失败仍撤销；迟到成功不能恢复已撤销权限。

真实Node中继增加内部发送完成边界，确保异步证书复核完成并将消息写入WebSocket后才放行下一次发送。既有request仍等待confirmation，运动命令没有流水化或重试。完整实现、测试环境限制见[续期修复说明](2026-11-02-sdk-renewal-pipeline.md)。

## 获批后具体执行

1. 创建云端 /var/backups/thirdhand/access-sdk-pipeline-20261102（0700），上传下述固定cloud.delta.json.gz与apply_sdk_pipeline_cloud.py（0600），核对摘要。
2. 默认只读前检，核对线上4657件清单、原current和受保护配置。基线变动立即停止，不覆盖其他任务。
3. 已有部署锁、零租约/零在途命令准入通过后，备份旧current和配置摘要；复制发布，仅替换两份源码；切换current，仅重启thirdhand-stage.service。
4. 验证清单、受保护配置和explicit-read-only健康。API重启会短暂断开浏览器/设备通道，并按原规则重建。
5. 继续已获准的观察员授权验收；前置授权稳定后才显式确认连接SDK，允许此前已批准的初始化使能及默认闭爪；不发送后续运动、不自动重试初始化。连续10分钟实测与本地SDK/网页/入库比较结果单独记录，未满足则不记通过。

不改Ubuntu、数据库、角色、权限、凭据、网络、端口、相机、展示站或运行依赖。不改变浏览器500ms、签名/设备1000ms、原中继请求超时及普通8/优先停止9个请求容量。签名不预先赋予未来时间，到期租约不复活；持续网络阻塞超过原期限仍必须断开。其他任务未提交相机代码不进入包。

## 固定清单

- 源码提交：c3ef04585e4b0eb99ef11aa1bdfda5d46f641369。
- 原发布：/opt/thirdhand-stage/releases/1cae07dc97cc0d04。
- 原清单：1cae07dc97cc0d04e2e9b88e8bc5eee9fa6f3cde60f11c7f2e5d4b4603b46724。
- 新发布：/opt/thirdhand-stage/releases/805921eeb03285b8。
- 新清单：805921eeb03285b8b68a878c27870f69e116d68db7b26e05c9547c9fa1d3551d。
- 包293129字节，SHA256 df7e0f6ed3ceb3e336f210df142e50b4a46e628447d2c58cd920b98237f07bef。
- 应用器SHA256 20acbdd58c1f071798e0ba0906ac1f996f0600b98f4d3b153e24af2a6ef34305。

| 更新文件 | 新SHA256 |
|---|---|
| services/cloud-api/src/control/leases.js | 6b4d09ec8035cec55b915fc23cb1ed9853c24639fec5ebbafca56ff6709b8320 |
| services/device-relay/src/server.js | 7c97806e1974bc04451cc19cc1442a0660b2c886315ab9ac3380178077b723cf |

总文件4657件，仅改变2件、保留4655件，无新增/删除源文件。包从固定Git提交构建，不读取脏源码。

## 测试与回退

新增旧实现先失败的ACK延迟用例；6项续期边界覆盖最大在途数、单事件合并、无心跳不续期、到期/撤销/拒绝、乱序确认和慢数据库；真实mTLS/WebSocket测试证明发送与ACK分离且凭据吊销仍拒绝。最终完整本地公网访问364/364通过、零跳过，五类固定包测试21/21通过。均为合成设备，不冒充真实SDK验收。

构建命令：python tools/deploy/build_sdk_pipeline_release.py --baseline .superpowers/sdd/2026-11-01-sdk-source-audit/sdk-diagnostic-candidate/expected-manifest.json --destination <新的空目录>。

云端先python3 apply_sdk_pipeline_cloud.py只读核验；获批后--apply。失败自动回退；必要时同目录--rollback恢复1cae07dc97cc0d04，只重启业务API，核验备份和原清单。无数据库迁移或权限变化，不回滚用户数据。回退不依赖新包完整性；发现其他任务发布或配置漂移则停止。

此次改变两份源码中的发送调度，超出上次单文件诊断固定候选。依据已批准[C8方案](2026-11-01-C8-ui-sdk-audit-and-design.md)第9节第6步，材料完成后申请本组实际部署确认；已批准的SDK只读验收范围持续有效。

## 实际部署与验收（2026-11-02，时间均为北京时间）

用户明确批准上传、部署并继续验收。部署前核对候选cdf9c84及CI运行41375674982成功；固定包与应用器上传至上述0700目录，文件0600，摘要相符。完整清单与受保护配置前检、零租约/零在途命令准入通过。应用器返回applied=true、exit=0；current切换至805921eeb03285b8，4657件清单验证通过，仅两件源码改变，thirdhand-stage.service为active。没有修改Ubuntu、数据库、网络或安全期限，没有执行SDK初始化或后续运动。

| 现场授权 | 请求 / 确认 / 释放 | 最终续期序号 | 结果 |
|---|---|---:|---|
| 第一次 | 10:27:20.840 / 20.897 / 26.297 | 20 | renewal_unconfirmed；四条迟到确认返回LEASE_SCOPE_CHANGED |
| 新Observer登录后第二次 | 10:32:33.147 / 33.205 / 55.933 | 88 | renewal_unconfirmed；三条LEASE_SCOPE_CHANGED、一条DEVICE_REQUEST_REJECTED |

第二次确认至释放22.728秒；序号88是云端续期序号，不代表88条均已被设备接受。Ubuntu最后记录的成功renew在10:32:54.109，10:32:55.033记录撤销，10:32:55.048记录remote_lease_expired，随后停止回执为ALREADY_STOPPED。页面显示“控制连接已过期，请重新申请控制权”；同一Observer登录仍在，没有将本次问题归因于登录失效。SDK保持断开、readOnly=true。

云端第二次四条失败诊断elapsedMs为1655/1410/1160/891；此计时包含失败处理及等待撤销，不能直接当作单向网络或纯ACK往返延迟。设备LEASE_SCOPE_CHANGED也可能是本地租约到期被清除后的返回，不能据此判断观察员权限错误。

复测后对Ubuntu本地只读context接口采样60次：0错误，p50=0.71ms、p95=1.08ms、最大2.39ms，采样期间SDK均未连接，系统NTP同步为yes。这只能排除该采样窗口内持续的本地接口缓慢，不能排除故障瞬间的停顿。此前独立TCP元数据已有下行重传证据，但当前窗口未采集对应包时序，尚不能把本轮所有迟到精确归因到校园网。

证据保存在本地忽略目录.superpowers/sdd/2026-11-01-sdk-source-audit/：sdk-pipeline-applied.png、sdk-pipeline-second-result.png、sdk-pipeline-second-diagnostic.png。未收集凭据、完整HTTP载荷或用户密码。

结论：部署完成，合成回归通过，真实稳定性验收失败。没有满足连续10分钟的授权前提，所以没有开始SDK初始化及真实状态采集。保留当前有界发送修复，不通过延长期限或自动重试初始化掩盖失败。后续应在一次同时间窗内关联云端签发/写入、Ubuntu接收/本地提交/回执的最小化时序与TCP元数据，明确延迟段后再准备针对性候选；新增运行端诊断源码仍须遵守固定候选部署流程。运动门禁继续保留。
