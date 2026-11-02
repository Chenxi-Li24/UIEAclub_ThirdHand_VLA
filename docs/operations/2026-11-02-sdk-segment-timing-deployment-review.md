# SDK 分段计时固定候选部署审阅

状态：固定包已获批并部署，已取得3条完整关联的真实续期记录；两端临时诊断开关已关闭。发现并离线复现毫秒级时钟差造成的租约校验拒绝，尚未上线逻辑修复；详细证据、申请次数偏差及收尾见[实际记录](2026-11-02-sdk-segment-timing-change.md)。此次部署只做D1诊断，不实施[权限分离方案](2026-11-02-sdk-separation-design.md)，不改变任何超时或租约有效期。

## 固定候选

- 源码提交：2bc817ce9249eece16b66da13339c5746458fab3。
- 本地包：.superpowers/sdd/2026-11-01-sdk-source-audit/segment-timing-candidate/sdk-timing-candidate.json.gz。
- 包大小729140字节；SHA256：d384a758c4fdee7553af194b1140c591c2d183ddecdf2e3b92cf62a13f0c5a92。
- 云端原发布：/opt/thirdhand-stage/releases/805921eeb03285b8；原清单SHA256：805921eeb03285b8b68a878c27870f69e116d68db7b26e05c9547c9fa1d3551d。
- 云端新发布：/opt/thirdhand-stage/releases/f72e61d85009b7ea；新清单SHA256：f72e61d85009b7eafb8f9447c6638dde0968dde84eec9e30e6991db931b9bf44。
- Ubuntu原代理：/home/nieqingcao/.local/share/thirdhand-stage-device/20261031/agent-sdk-ab786c269838e18c。
- Ubuntu新代理：/home/nieqingcao/.local/share/thirdhand-stage-device/20261031/agent-sdk-timing-80ec1265764b8569。

| 位置／文件 | 操作 | 新SHA256 |
|---|---|---|
| cloud: services/cloud-api/src/control/leases.js | 替换 | ae99f890ecb95624fc85ba11ff2f783e375cb34b5053e762d914a89010a46fbb |
| cloud: services/device-relay/src/server.js | 替换 | 6b908235d836052fb76e0d0a627c0801cfbd383c2adf5bd6bca449b92a44e201 |
| cloud: services/device-relay/src/lease-timing.js | 新增 | fd01dbe5bc2d7ed1e54d8bc341186819d5765c4849e59ddb06a91802c60c436b |
| edge: thirdhand_edge/bound_transport.py | 替换 | 52f4b9d5b97e69e37637e4635f31b6baef4fa8ed413b49f2af1f0ba7e023594b |
| edge: thirdhand_edge/lease_timing.py | 新增 | 1d1a37325da0f16818aa8843917268760c7ba5cf1c79b8843cad3e4478141b14 |

云端清单4657→4658，原4655件保持；Ubuntu23→24件，原22件保持。Ubuntu现场bound_transport.py摘要已与修改前Git一致，unitHashes和完整源清单随包固定。包只从固定Git提交读取5件源码，不读取当前工作树的相机改动、配置秘密或数据库。

## 具体应用范围与准入

1. 云端创建/var/backups/thirdhand/access-sdk-timing-20261102、Ubuntu创建/home/nieqingcao/.local/share/thirdhand-stage-device/SDK-timing-20261102，目录0700，上传本固定包0600；先核对SHA，再只读检查包schema、路径、文件清单及每件摘要。使用现有受核验部署锁与零租约准入，不直接覆盖current中的文件。
2. 云端核对原current、完整4657件清单和现有配置；Ubuntu核对包中23件源码、主服务与两个既有drop-in的摘要、有效PYTHONPATH及NeedDaemonReload=no。原Robot服务路径不变。任何漂移停止并重新整理候选，不能覆盖其他任务。
3. 保存云端current、服务配置摘要、Ubuntu有效路径/主unit/drop-in摘要及服务状态。确认云端活动租约和在途命令均0、Ubuntu sdkConnected=false且readOnly=true；获取有界部署准入后暂停代理切换。未满足时不强制停止正在使用的SDK。
4. 云端复制旧发布到新路径，仅替换2件和新增1件，写入包内新manifest，完整校验4658件；Ubuntu复制有效代理快照到新路径，仅替换1件和新增1件，完整校验24件。保留旧目录，禁止用本地整个仓库覆盖现场目录。
5. 云端新增/etc/systemd/system/thirdhand-stage.service.d/zzzz-sdk-segment-timing.conf，仅含`[Service]`和`Environment=THIRDHAND_SDK_TIMING=1`。若目标已存在或有更后置冲突配置，停止，不覆盖。
6. Ubuntu新增/home/nieqingcao/.config/systemd/user/thirdhand-stage-edge-read-only.service.d/zzzz-sdk-segment-timing.conf，仅含`[Service]`、`Environment=PYTHONPATH=/home/nieqingcao/.local/share/thirdhand-stage-device/20261031/agent-sdk-timing-80ec1265764b8569`、`Environment=THIRDHAND_SDK_TIMING=1`。保留既有50-C3c-transport.conf和zzz-sdk-scope-state.conf，检查有效路径确实切换；不修改Robot unit。
7. 切换云端current，分别daemon-reload并重启thirdhand-stage.service与thirdhand-stage-edge-read-only.service。代理管理的采集／上传／相机子进程可能短暂重连；恢复后核对服务、设备绑定、采集健康和只读门禁。没有新SDK初始化，权限表、数据库和运动入口均不改。

上述步骤为固定人工应用规程，构建工具只产出包，不会执行服务器命令；不复用上一个只允许2件文件的pipeline应用器绕过其范围校验。实施时对应用操作使用已批准的这份清单，所有新目录均为已明确的绝对路径。

## 有界诊断、收尾与回退

Observer只申请sdk授权，不点击连接SDK；最多3次、总计时窗口10分钟，取得完整故障链即可结束。签名、浏览器新鲜度、ACK超时、续期并发、运动门禁不变。只提取匿名sdk_segment_timing记录，不收集HTTP载荷、令牌或原始签名；用summarize_sdk_timing.py离线汇总，不在网页公开日志。

日志默认关闭；环境开关启用后每个记录器最多600秒／12000条。进程重启会重新开始窗口，因此自动限时不替代清理。收尾核对无租约、无SDK连接后，将两端本次drop-in中计时开关改为0，保留Ubuntu新路径，daemon-reload并重启这两个服务，验证日志关闭。仅修改与上述确切内容相符的本次文件；发现漂移则停止。此收尾也在本次批准范围，防止诊断长期驻留。

失败回退：在零租约、SDK断开下停止本次代理；核对本次drop-in仍为准确内容后移除本次两件drop-in，云端current恢复805921eeb03285b8、Ubuntu由原zzz-sdk-scope-state.conf恢复ab786c269838e18c；daemon-reload后启动/重启上述两个服务，复核原完整清单与绑定。不删除新旧快照、不回滚数据库或用户数据；不重启Robot、不重载Nginx、不修改Wi-Fi或Tailscale。未知停止状态不自行恢复连接。

## 验证与审批原因

本地公网访问366/366、Python网关92/92通过，包含真实本机PostgreSQL、mTLS/WebSocket＋Python网关的匿名摘要关联；新断言验证ACK时间不包含等待撤销、诊断sink异常不阻止安全处理、默认关闭、窗口／条数封顶、非sdk和运动消息不跟踪。均为合成设备，不是现场诊断或SDK验收。部署前再核对最终CI。

固定包测试3项及源码边界5项共8/8通过。首轮CI的public-access通过，通用源码边界发现构建器写死Ubuntu用户名目录；已改为从现场基线读取并校验绝对POSIX路径和固定相对目录，未放宽边界检查。重建包SHA256与上表完全一致，部署5件源码未改变。最终代码提交5bd2b7ba5759a3d316838df9daad763592d91d12的[CI 41382538357](https://github.com/Oliveirah007/UIEAclub_ThirdHand_VLA/actions/runs/41382538357)中public-access和test均成功；后续仅补记审阅状态与设计说明，不改变固定运行源码。

实际变更新增云端诊断模块、Ubuntu诊断模块及两个服务drop-in，超出上一组两文件cloud-only候选。此次确认依据已批准C8流程“固定候选材料完成后申请实际部署”；本次申请只涵盖以上5件源码、2件drop-in、两个现有服务重启、诊断和收尾/回退。SDK连接／读取／运动权限分离和单次有效期延长均不在本次上线范围。
