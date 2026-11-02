# SDK 有界续期发送修复部署审阅

状态：固定候选已构建，本地完整公网访问364/364与固定包边界21/21通过；尚未上传、尚未部署。最终CI在实际部署前核对。当前线上为1cae07dc97cc0d04诊断版本，真实十分钟验收未通过。

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
