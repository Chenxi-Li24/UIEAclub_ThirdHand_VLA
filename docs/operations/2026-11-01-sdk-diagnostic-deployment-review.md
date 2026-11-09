# SDK 确认拒绝诊断固定部署审阅

状态：用户已明确批准上传、部署并继续验收。2026-11-02 09:37（北京时间）已应用为1cae07dc97cc0d04，前检和应用exit=0，applied=true；仅改变leases.js，保留4656件。诊断已部署不等于SDK已修复，现场验收见文末。

## 目的与限制

目前云端只记录LEASE_UNCONFIRMED，不能判断设备拒绝原因。新增日志只记录固定组件sdk_lease_confirmation、grant/renewal、白名单设备状态和错误码、三个绑定是否匹配的布尔值。未知值替换为UNRECOGNIZED；不记录实际标识、异常全文、响应载荷、凭据、签名或账户数据。日志写入已有业务服务journal，无新增外传目的地。

只在原有拒绝分支增加日志，不改授权判断、成功路径、500ms/1000ms期限、角色、readOnly、运动门禁或重试。设备若仅返回DEVICE_REQUEST_REJECTED，仍须继续缩小设备内部原因；此候选不保证单独解决连接问题。

## 固定操作与影响

1. 新建 /var/backups/thirdhand/access-sdk-diagnostic-20261101（root 0700），上传固定cloud.delta.json.gz和apply_sdk_diagnostic_cloud.py，文件仅root可写。
2. 核对摘要；默认只读审阅4657件线上清单、受保护配置、业务健康。基线漂移立即停止，不覆盖其他任务。
3. 沿用部署锁及零租约/零在途命令保护，备份原current/配置摘要，从原发布复制后仅替换services/cloud-api/src/control/leases.js。
4. 切换current，仅重启thirdhand-stage.service；因此短暂断开网页和设备业务通道。健康必须保持explicit-read-only，受保护配置不得变化。
5. 继续已获准的Observer授权与真实状态验收，先不初始化SDK；授权稳定后才显式确认初始化。允许原先批准的使能/默认闭爪，但不发送后续运动，不自动重试初始化。

不改Ubuntu、相机、数据库、网络、端口、凭据、角色或安全超时。其他任务未提交的相机代码不在包内。

## 固定摘要

- 源码提交：e54811171d64dc49dc12bc86537979a00893a2b2。
- 原发布：/opt/thirdhand-stage/releases/671809219c9cefc8。
- 原清单：671809219c9cefc81997774a77e83dc791f8b725541a76d5da9e663bd4e5f990。
- 新发布：/opt/thirdhand-stage/releases/1cae07dc97cc0d04。
- 新清单：1cae07dc97cc0d04e2e9b88e8bc5eee9fa6f3cde60f11c7f2e5d4b4603b46724。
- leases.js：c56a222f51c59860ffffa49390468a7b50b1b2f2443fe47fffcf46fc3f7ae3d3。
- 包285160字节，SHA256：3186e5d5acf93de5b7bc7c401de861d91aebd01ed0d59a90073f9ad0c0d73bf3。
- 应用器SHA256：0209e6d302af8b434c3e24224dbca24cd6356be32d083cf759d38fb2ac2f3a4a。
- 总4657件，改变1件、保留4656件，无增删文件。

## 验证、启动与回退

本地真实隔离PostgreSQL：新增脱敏/拒绝5项、续期7项、租约/权限/心跳/WebSocket9项，共21项通过。四类固定包测试17项通过，覆盖多余文件、内容篡改、摘要不符；初次pytest临时目录权限失败，指定工作区独立临时目录后重跑通过。测试使用合成设备，不代表真实SDK通过。最终CI须在实际上传前核对。

构建：python tools/deploy/build_sdk_diagnostic_release.py --baseline .superpowers/sdd/2026-11-01-sdk-source-audit/sdk-renewal-candidate/expected-manifest.json --destination <新的空目录>。从固定Git提交读取，不使用脏工作区源码；无新依赖或配置。

云端先python3 apply_sdk_diagnostic_cloud.py只读核验，获批后--apply。失败自动恢复旧发布；必要时同目录执行--rollback，仅恢复原current并重启业务API。回退核验原清单和备份，不回滚数据库，不删除用户记录，不依赖新包完整性。

本次新增固定字节与上传目标不在上一份两文件续期包中，因此依据已批准[C8方案](2026-11-01-C8-ui-sdk-audit-and-design.md)第9节第6步，在材料准备好后申请本次部署确认。原批准的SDK只读验收权限持续有效。

## 2026-11-02 实际部署与验收

- 上传前复核current仍为671809219c9cefc8，清单、源码摘要与原固定基线一致；上传两件文件摘要匹配，目录0700、文件0600。只读前检及应用成功，受保护配置和explicit-read-only健康校验由固定应用器完成。
- 09:38:19.698 Observer申请，09:38:19.887确认，09:38:23.409释放，renewal_sequence=10，renewal_unconfirmed。
- 新诊断明确：phase=renewal，deviceState=rejected，deviceCode=LEASE_SCOPE_CHANGED，三个绑定比较为false；续期诊断耗时919ms。
- Ubuntu已有事件：09:38:19.828 arm成功，随后9次renew成功，最后09:38:22.278；09:38:23.086先执行租约撤销，09:38:23.090记录lease_expired。设备源码在先调用expire清空lease后，使用lease?.scope与请求scope比较，因而这次过期也会返回LEASE_SCOPE_CHANGED。不能把它误判为观察员权限升级失败。
- 本次自动化仅申请SDK授权，没有点击连接SDK或初始化确认，没有发送后续运动。部署前读取sdkConnected=false、readOnly=true、controlAccepted=true、recordingHealthy=true；两个正确服务名thirdhand-tcp-calibration-robot.service和thirdhand-stage-edge-read-only.service均active。早先查询猜测服务名得到inactive不代表实际服务停止。
- 连续10分钟真实SDK状态验收仍未通过。下一步在本地修复确认返回阻塞后续续期的调度，并保持原到期/权限规则；不能宣称其能修复超过一秒的持续下行阻塞。

云端结果文件：/var/backups/thirdhand/access-sdk-diagnostic-20261101/apply-output.json。截图：.superpowers/sdd/2026-11-01-sdk-source-audit/sdk-diagnostic-applied.png。CI候选aee5991运行41319221028的public-access/test均success。
