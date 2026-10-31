# C3e Ubuntu 软件失联保护：实际部署记录

**已部署，仍是永久只读层；本轮SDK连接和真机运动指令均为0。** 此项实现设备端软件取消与SDK释放，不证明机械臂物理停稳、失能或掉电保护。

## 实际版本和配置

2026-11-01 北京时间00:43:40左右（UTC epoch1793465020.4522774）安装器返回installed=true、readOnly=true、workerGuard=true、ready=true、sdkConnected=false、moving=false。使用云端checkedAt=1793464971594的零控制租约/零在途命令记录，各关键步骤仍在60秒有效期内完成；没有放宽有效期。

Robot新目录为`/home/nieqingcao/.local/share/thirdhand-stage-device/20261031/robot-6a801e6404e6265e`。准确37件公开文件归档SHA256为`6bc5ea3d994973a86dfcaabfdadd49ab280bc3ccd7f97be7773fb83241ff1fb8`；安装器SHA为`30e3de2e4a3be0ace7e43bf04a37cdecb2a8209c585774c7cfa448c9c13656ad`。具体差异与回退见[C3e审阅](2026-11-01-C3e-worker-watchdog-deployment-review.md)。

只新增Robot unit的`zz-c3e-worker-watchdog.conf`以覆盖ExecStart，保留90、95、99三个旧drop-in及旧robot目录。现场config.js和seed_joints_deg预览校验/传递保留。停止并恢复原只读edge agent、重启Robot；相机source/publisher配置、SDK/夹爪参数、限位、速度、CAN、证书、数据库、网络及端口均未修改。

## 验证证据

- 本地相关完整回归：Node321/321、Python233/233；这是并行账号改动合入前的固定源码范围，不是最终全仓测试结论。
- 保留现场策略的派生候选：Node56/56、Python35/35；安装器独立审查3项问题在一轮RED→GREEN修复后17/17通过。
- 实际Ubuntu独立SIM smoke（UTC1793463837.6955974）：保持stdin打开、不续期，worker自行取消模拟动作并释放模拟SDK。nativeSdkImported=false、canOpened=false、realMotionCommands=0、unitChanges=0、physicalStopState=unknown。
- 实际默认review先因SCP默认0664权限被public_input拒绝。固定摘要核验后，只将本次5件上传文件收紧到0600；原检查不改，随后review通过。没有绕过文件保护。
- 第一次维护交接因云端账号并行发布触发current断言，未切换Robot；第二次记录因工具往返已过期，在写入前被拒绝。最后预先建立等待公开JSON的SSH会话，保留新云端原时间戳交接，未重置其年龄，安装成功。
- 部署后UTC1793465080.014254：新目录所有摘要、旧目录31件摘要均匹配；实际Python worker脚本指向新目录；Robot PID330689、edge PID330708均active/running、NRestarts0。SDKfalse/movingfalse/stateReadyfalse，录制通道recordingHealthy=true。

设备context显示workerLeaseGuardRequired=true、softwareCancellation=true、controlledStop=false、independentHardwareWatchdog=false、videoHealthy=false。readOnly=true时controlAccepted=true仅表示只读连接/采集条件满足，不能解释为运动可用。没有通过实际SDK连接或实际运动来验证此软件保护。

## 并行账号版本

用户确认另一聊天“连接局域网Ubuntu电脑”正在做注册与管理员审批。根任务只读核对其最终发布`registration-approval-a570d928578cb5bb`保留本次新camera-view.js，设备控制仍explicit-read-only，相对C3f仅账号/网页/迁移文件改变。没有回退或覆盖其账号发布，也没有向该聊天发送消息。

## 保留的限制及下一验收点

1. Python监控需要线程能够运行。SDK持GIL、worker/OS整体挂死、断电等情形，没有独立硬件停止证明；cleanup不当作物理停止。
2. 用户允许夹爪0–100%，已记录；真实行程、夹爪停止反馈、六轴限位/坐标和新起点仍未核验。全运动门禁保持关闭。
3. 新相机前端已上线，但当前真实观看仍无解码帧。当前双路稳定基线和35秒故障复测未完成，不把自然不可用当成故障保护通过。

根任务证据位于本计划`worker-watchdog-deploy/actual-ubuntu-sim-result.json`、`actual-ubuntu-postcheck.json`；Ubuntu独立diagnostics目录保留sim-result-public.json、default-review-public.json、apply-result-public.json和postcheck-public.json。before-robot-6a801e6404e6265e保存固定baseline与状态；回退不依赖上传包完整，SDK未知则闭锁，未提供新鲜云端记录时不恢复edge agent。

自动审批曾拒绝广泛远端源码导出，理由是可能包含敏感代码/配置且超出元数据范围；该操作未执行。已用本地保存的公开部署包和只读远端哈希重建准确基线，无需该导出。

本聊天没有Git暂存、提交、push或PR；并行账号聊天已将其自身改动暂存，未被本聊天撤销。
