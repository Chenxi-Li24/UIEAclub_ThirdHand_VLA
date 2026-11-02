# SDK 授权验收结果与分范围租约修正

## 真实结果

浏览器心跳修复 a3ca345673912070 上线后，Observer 在前台设备页申请一次授权。2026-11-02 07:35:06.410Z 至 07:35:55.688Z，共49.278秒，数据库续约序号168，最终 released / renewal_unconfirmed。未达到连续600秒，验收不通过；不把申请授权视为SDK连接读取。

设备事件顺序：07:35:55.411Z 本地 lease_expired 触发只读释放；55.429Z worker记录 remote_lease_expired；55.643Z 云端 renewal_unconfirmed 再次释放，结果 ALREADY_STOPPED。云端随后收到3次 LEASE_SCOPE_CHANGED（986/686/387ms）。代码在租约为空时也比较 scope，导致到期误报成范围改变。该窗口没有 browser_control_timing 错误，不能据此宣称所有浏览器心跳问题已永久解决。

只读采样结束，SDK全程false、readOnly=true；云端活动租约0、部署后ops.commands计数0。未初始化SDK、未使能、未闭爪、未发送运动。设备侧到期是真实发生；现有常规日志不能再区分这次间隙来自网络、调度或本地执行停顿，不能把推测写成已证实网络根因。

本地证据：忽略目录 `.superpowers/sdd/2026-11-01-sdk-source-audit/browser-heartbeat-expiry-proof.png`、`browser-heartbeat-device-0732.jsonl`；云端私有备份目录 `access-sdk-browser-heartbeat-20261102/authorization-samples-0732.jsonl`。不提交原始账户、租约ID或凭据。

## 修正设计与实现（尚未上线）

| 边界 | SDK专用授权 | 管理员运动授权 |
|---|---:|---:|
| 浏览器心跳新鲜度 | 3000ms，保持已上线值 | 500ms，保持 |
| 单次签名租约、数据库有效期上限 | 3000ms | 1000ms，保持 |
| 设备单调截止上限 | min(签名跨度、剩余时长、3000ms、既有锚点) | 同式，上限1000ms |
| 云端续约调度 | 每250ms检查，保持 | 依赖新鲜浏览器回复，保持 |
| ACK与并发 | 1500ms、最多4条在途，保持 | 保持 |

这只是SDK授权抗抖动修正，不是完整的多人读取/独占运动分离。管理员以Administrator模式取得的仍为control租约，不会自动享受3秒SDK时长；管理员切换Observer模式与普通观察员适用相同规则。

实现跨云端签名、PostgreSQL仓库、edge验签、Robot policy/watchdog、Node桥接和Python guard一致传递scope。省略scope的历史内部消息按control/1秒处理。sdk范围不可经续约、排队命令或伪造字段升级为control。Node与Python在现有上层鉴权外再次拒绝SDK租约发送运动。SDK构造仍仅在用户明确点击连接后调用，保留其已告知的使能/默认闭爪副作用。

真正过期、撤销、角色变化、会话变化、旧epoch和旧序号不能复活；新连接必须显式申请新授权。修正空租约的错误分类为STALE_LEASE，真正scope变化仍返回LEASE_SCOPE_CHANGED。运动readOnly门禁保持。

代价：设备失去云端续约后，SDK连接最多保留至最后一次有效签名的3秒截止；若浏览器先失联而云端尚在3秒容忍内续约，且撤销包同时丢失，两个窗口可叠加接近6秒。该窗口只授权SDK连接/读取，不是运动权限；软件释放不等于硬件停止保证。超过1500ms的ACK失败、长时间网络中断仍会撤销，不能承诺本改动解决所有掉线。

## 资源、启动与部署边界

不新增数据库表、迁移、账户权限、依赖、端口、网络或相机配置。正常本地/云端启动方式不变。需要云端更新2件源码，Ubuntu更新1件edge和5件Robot源码，并使用各自独立快照和2件入口drop-in；旧版本保留。实际Ubuntu Python桥接包含另一个任务的IK seed功能，打包必须从实际源码局部应用本次改动，完整保留该功能，不得整体覆盖。

本轮只在本地实现和测试。此前批准的固定包明确设备单次租约仍1秒，因此新的3秒包须在固定候选、完整摘要、测试和回退材料准备好后单独审阅；没有把“允许放宽超时”解释为已批准任意服务器包。

## 验证

本地最终业务回归405/405、Python edge/worker157/157通过，源码边界审计ready。最初回归发现两个旧测试仍假设SDK签名固定1秒，已按新scope规则调整；另发现短签名在正时钟偏差下可能被放到scope上限，已额外按签名本身跨度裁剪，原时钟偏差回归不放宽断言并通过。

使用现有public-access隔离PostgreSQL测试、Node policy/watchdog/bridge测试、Python edge及worker模拟测试。覆盖SDK跨1.5秒间隔续约、3秒边界、control仍1秒、签名1秒即使有时钟偏差也不得变长、过期终止、scope不可升级和多层运动拒绝。真实10分钟授权稳定性和真实SDK读取均待新包获批上线后验收；本轮不继续重复申请掩盖失败。
