# C3e Ubuntu Robot 软件通信租约保护候选

实际状态补充：候选已通过Ubuntu独立SIM和默认review并完成只读部署，具体时间、后核对和限制见[实际变更记录](2026-11-01-C3e-worker-watchdog-change.md)。下文保留原部署审阅范围。

范围：只在独立目录部署软件保护；永久只读，不连接SDK，不发送运动，不调整网络、相机或数据库。实际远端变更由root执行。本文件和helper均为本地准备，尚未部署。

## 已核对基线

- 主机：Ubuntu / uid1000，`nieqingcao@100.85.63.78`，SSH HostKeyAlias `192.168.58.68`。
- 原目录：`/home/nieqingcao/.local/share/thirdhand-stage-device/20261031/robot`。公开31文件哈希全部与C3a最终记录一致。
- `/health`：connected=false、moving=false、stateReady=false。该状态不是物理停机验收证据。
- Robot unit活动，采样MainPID=86836；已加载与磁盘实际drop-in均仅90-main-directory-step1.conf、95-meituan-speed20.conf、99-read-only-sdk.conf，全部固定哈希、无符号链接。其他配置继承，不删改。
- 原始公开源码由已有本地C3 tar与contracts重建，31/31字节哈希匹配。没有从远端导出源码，没有读取私钥、token或环境凭据。

首次较广源码导出被自动审批拒绝，原因为导出范围超出metadata/hash基线授权且可能包含敏感代码配置。该操作未执行；之后仅采metadata/hash，并复用了已有本地公开产物。

## 最小生产差异

7个旧文件调整：server.js、robot-controller.js、startouch-bridge.js、startouch_bridge.py、remote-gateway.js、control-policy.js、lease-watchdog.js。新增3个模块：remote_lease_guard.py、software-stop-adapter.js、stop-evidence.js。

- config.js保持原字节；关节限位、速度配置、连续跟随等其他现场文件保持原字节。
- server沿用旧远端专用服务与硬编码readOnly:true、拒绝全部WebSocket升级；仅强制worker guard并要求协议配对。
- controller采用冻结停止未知语义/关联ID/并发停止门与租约审计转发，保留现场seed_joints_deg校验与传递。
- Python采用冻结worker guard，恢复现场seed_joints_deg的校验与q_seed选择；新租约门仍先执行。
- 软件保护会尽力取消/释放SDK，默认不支持已核验的controlled stop，绝不把cleanup当成物理停稳或失能。

精确统一差异位于候选中的`review/site-to-candidate.patch`，输入源码指纹位于`review/source-pins.json`。

## 固定候选

- tar：`C3e-robot-worker-watchdog-candidate.tar.gz`，37个普通文件，83610字节；无二进制/SDK/模型/凭据。
- SHA256：`6bc5ea3d994973a86dfcaabfdadd49ab280bc3ccd7f97be7773fb83241ff1fb8`。
- 新目录：`robot-6a801e6404e6265e`，原robot目录不改。
- baseline JSON SHA：`9b282f0bb67d1a84fff03f83107b554b05514b5826532cc1fb2d76b58aa0d43b`。
- package JSON SHA：`e902ed8a2501930507ed84f5671deda4985a678882f874002a6b608bf628223d`。
- 新manifest SHA：`960042d65c18842ae79b870ecb1e8a8c483faf55c4165e29dc3e507b0fe247b0`。

## 操作与回退

helper默认review；apply必须显式`--mode apply`。root将公开tar、package JSON、baseline JSON与helper放入原BASE/incoming，保持owner1000且不可被组/其他用户写入。默认review只读核对，不创建远端目录或修改unit。

apply另要求60秒内云端clearance文件：schema=1、phase=C3e、指定deviceId、checkedAt为UTC毫秒、activeLeases=0、activeCommands=0、sdkConnected=false、moving=false。root通过既有只读云端流程获取，helper不访问云端凭据。

1. 固定旧31哈希、unit与3个drop-in、MainPID及未连接/运动状态；枚举实际磁盘*.conf并核对已加载列表，拒绝未reload的额外文件及符号链接；确认固定归档/metadata/manifest和已审阅10文件差异。
2. 获取原`/tmp/thirdhand-robot-can0.lock`排他锁，不截断或替换锁；停止只读edge agent，再核对SDK未连接、未运动。
3. 在独立目录展开白名单文件；纯Node require预检不创建服务或导入SDK。
4. 新增唯一`zz-c3e-worker-watchdog.conf`，只覆盖ExecStart，其他drop-in全部继承；每次关键提交/reload/restart前再次核对磁盘、旧单元/3文件哈希和60秒freshzero，重载后必须实际加载本次drop-in。
5. 等待ready且SDK仍未连接/运动，复核旧目录未变；恢复agent前后及最终成功前再次验证同一freshzero，过期即进入回退。全程不发送connect或运动命令。

第一次服务变更起共用错误处理，包含展开、Node require预检、尚未创建新drop-in等失败。rollback不需要上传tar/package或候选文件完整，使用before目录内固定哈希baseline和状态备份；新drop-in尚不存在时同样可恢复已知安全的旧只读Robot。仅移除哈希匹配的本次新drop-in，保留所有旧drop-in和两个源码目录。

显式或自动rollback默认保持edge agent停止；只有另提供仍在60秒内的freshzero且原agent曾活动时才恢复，并在恢复后再次验证。SDK状态未知、连接中、运动中、health不可用或回退失败时不恢复旧入口，停止agent/Robot并写rollback-blocked标记，须人工复核。没有物理停止证据时不会声称机械臂已停止。

示例（均仅由root在审阅通过后执行）：

```sh
python3 install_candidate.py --baseline BASE/incoming/baseline-public.json --package BASE/incoming/candidate-package.json --archive BASE/incoming/C3e-robot-worker-watchdog-candidate.tar.gz
python3 install_candidate.py --mode apply --baseline BASE/incoming/baseline-public.json --package BASE/incoming/candidate-package.json --archive BASE/incoming/C3e-robot-worker-watchdog-candidate.tar.gz --clearance BASE/incoming/C3e-clearance.json
python3 install_candidate.py --mode rollback
```

上面BASE须替换为已固定的Ubuntu绝对路径；helper会拒绝其他位置。

## 验证

派生隔离候选Node24测试56/56、Python35/35，包含现场IK seed保留、worker过期、真实SIMULATE子进程及Node暂停时软件清理；不含真实SDK/CAN或运动验收。builder/helper原10项通过；独立审阅发现3项并完成一轮修复后17/17通过，新增未reload/中途foreign drop-in、61秒过期、无clearance回退不恢复agent、pre-DROP预检失败恢复等回归，见review-fix-green.txt；最终指纹见deployment-preparation-pins.json。

额外`ubuntu_sim_smoke.py`不进入37件生产tar。root可在独立诊断目录展开受审候选后运行：

```sh
python3 ubuntu_sim_smoke.py --candidate-root /absolute/isolated/candidate --worker-python /absolute/known/python
```

脚本固定核验候选Python/guard哈希，强制SIMULATE=1、REQUIRE_CAN_RX=0与模拟CAN名，保持stdin打开且不续期，验证软件自行取消与模拟cleanup，并报告physical unknown。本地派生候选实跑通过，见ubuntu-sim-local-green.txt；Ubuntu执行仍由root负责，尚未声称已完成。

保护边界：SDK构造/调用持有GIL、Python/OS整体暂停、进程/供电故障时，软件监视线程不能保证执行。网络不作修改；独立硬件停止仍未验收，真机运动保持关闭。
