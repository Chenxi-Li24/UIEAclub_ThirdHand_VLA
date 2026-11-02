# SDK时钟修复固定部署审阅

状态：本地完成、待批准上线。运行源码固定提交 `5f1854b801cdf9c020a21c199c8abbff98cef256`；本文件不代表已上线或真实SDK验收通过。

## 固定包与差异

- 包：`.superpowers/sdd/2026-11-01-sdk-source-audit/clock-candidate/sdk-clock-candidate.json.gz`。
- 大小：726046 字节；SHA256：`95aa0305d59a1811c3a6a34cdfbe5e99df64b4fd3996e34ce210dcff5aa37ce5`。
- 云端原发布：`/opt/thirdhand-stage/releases/e3f0176566d900ed`，原清单SHA256：`e3f0176566d900ed4ee3c576778df465e02de7abbc2284c245b804e93f526877`。
- 云端新发布：`/opt/thirdhand-stage/releases/d5284b8679ff90e8`，新清单SHA256：`d5284b8679ff90e88f0c2138e8b31c9eb53f6197ddef09eb2982300943fc97b7`。
- 云端4658件仅替换2件，保留4656件；Ubuntu代理24件仅替换1件，Robot 37件仅替换2件，其余内容原样保留。清单中的历史manifest保留用于来源追溯，本包before/after为本次完整摘要权威。

| 位置／文件 | 新SHA256 |
|---|---|
| cloud: apps/web/public/js/admin-control.js | `2bfa72d5908f29edab553bd5dac28655ab147450249a2bc09d891b324c28bdfb` |
| cloud: apps/web/public/js/i18n-cloud-catalog.js | `2fce1e7ba6a27eb57747556fead2ffb4d4ef46c014e1263e83bc445e0d5f0b2d` |
| edge: thirdhand_edge/lease.py | `07ee5a31d3e04e6e99fa5e0501efc8db793b2ce69382c4dd0e13a7fc63eb2d98` |
| robot: services/robot/src/control-policy.js | `7d260d6ae9edc661920ef8ef4d508a3613b015f0a38106f0382bfab269dd471b` |
| robot: services/robot/src/remote_lease_guard.py | `3f548dc95229010b199a7206475303e0ab3637b75f5ec1fc0537fb044d3b6dfc` |

## Ubuntu有效路径与服务配置

### edge

- 原路径：`/home/nieqingcao/.local/share/thirdhand-stage-device/20261031/agent-sdk-timing-80ec1265764b8569`。
- 新路径：`/home/nieqingcao/.local/share/thirdhand-stage-device/20261031/agent-sdk-clock-a963153d56dac68d`。
- 仅新增：`/home/nieqingcao/.config/systemd/user/thirdhand-stage-edge-read-only.service.d/zzzzz-sdk-clock.conf`。
- 内容SHA256：`eb35d02a029f025baafbf11dcc118412707b99e9d6a783a90c5a617d869cdb41`。

```ini
[Service]
Environment=PYTHONPATH=/home/nieqingcao/.local/share/thirdhand-stage-device/20261031/agent-sdk-clock-a963153d56dac68d
Environment=THIRDHAND_SDK_TIMING=0
```

### robot

- 原路径：`/home/nieqingcao/.local/share/thirdhand-stage-device/20261031/robot-sdk-2fe4b77d3974d3c3`。
- 新路径：`/home/nieqingcao/.local/share/thirdhand-stage-device/20261031/robot-sdk-clock-26c8339436ca6daa`。
- 仅新增：`/home/nieqingcao/.config/systemd/user/thirdhand-tcp-calibration-robot.service.d/zzzzz-sdk-clock.conf`。
- 内容SHA256：`85fbd74e26ce0eff25b4c5b7beb46a89669892a334f4b035fe36dc4f7d9150de`。

```ini
[Service]
ExecStart=
ExecStart=/home/nieqingcao/ThirdHand/UIEAclub_ThirdHand_VLA/local/runtimes/node/bin/node /home/nieqingcao/.local/share/thirdhand-stage-device/20261031/robot-sdk-clock-26c8339436ca6daa/services/robot/src/server.js
```

现有unit和drop-in全部保留，包内固定摘要；若出现额外/更后置配置、NeedDaemonReload=yes、有效入口不符，停止而不覆盖。THIRDHAND_SDK_TIMING保持0。没有改超时、租约上限、readOnly或账户权限。

## 应用规程与准入

1. 经批准后，仅上传本固定包至云端`/var/backups/thirdhand/access-sdk-clock-20261102/`和Ubuntu用户目录下`.local/share/thirdhand-stage-device/SDK-clock-20261102/`，目录0700、包0600；摘要验证后解包检查schema、purpose、固定5件文件、before/after完整清单、文件内容SHA。包不含密码、令牌、配置秘密或数据库。
2. 云端核对current仍为上述原发布及完整清单，记录业务环境/服务配置/展示站摘要；使用现有经摘要核验的installation_lock和quiescent_lease_admission准入。活动租约(requested/active/revoking)和在途命令须为0。设备context须sdkConnected=false、readOnly=true；现场三件修改前源码、24/37件完整源清单、unit/drop-in摘要均与包相符。发现任何漂移即停止，不自动扩大范围。
3. 保存current、原路径、服务状态与全部配置摘要为before-public.json；原目录和原配置不覆盖。两个新快照必须不存在，从现场有效目录复制（仅忽略__pycache__），应用固定的1+2源码增量，验证全量after摘要。云端复制原发布到指定新目录，只替换2件并写入包内新manifest，验证全量4658件。
4. 在零租约准入锁保护下协调切换，先暂停Ubuntu代理，再切换Robot入口；创建上表两个准确内容的drop-in，daemon-reload，仅重启Robot和代理两个既有用户服务。核对有效PYTHONPATH、ExecStart、实际进程路径和readOnly，服务启动本身不得初始化SDK。代理管理的相机/采集会短暂重连。
5. 云端再次核对保护摘要和零租约准入，原子切换current到新发布，仅重启thirdhand-stage.service。核对healthz、完整发布清单、静态资源版本、设备绑定、采集健康和SDK仍断开；三个服务之外不重启、不重载Nginx，不新增端口或数据库变更。
6. 上述为固定人工应用规程，可通过宝塔终端和既有SSH执行；构建工具仅产出固定包，不自动上传/运行。部署使用已核验的既有锁和准入辅助函数；不修改这些辅助文件，也不以旧应用器绕过文件范围限制。操作前复核云端当前基线，前次发布记录不能替代此核验。

## 验收与回退

先以Observer进行最多3次、总窗口不超过10分钟的真实授权申请/续期验证，只申请、不点击Connect SDK。核对等待提示/禁用/恢复、有效租约反馈、错误原因、主动释放及本地1秒到期门禁。诊断开关保持关闭，不扩大日志范围，不发初始化、后续运动或改网络。用已有journal白名单结果确认，不读取凭据。浏览器会话过期时由用户本人登录。
若仍失效，保留具体拒绝码，停止重复申请；不得放宽500ms/1000ms/1500ms或在途上限。授权稳定不等于SDK真实连续10分钟状态验收，两者分开报告。
回退仅在零租约、SDK断开时执行：停止代理，核对两个新增drop-in仍等于包内内容后仅移除这两件，daemon-reload并重启Robot/代理，恢复旧有效路径；云端current恢复e3f0176566d900ed并重启业务API。重新验证旧完整清单、设备绑定和只读状态。保留新旧发布、数据库与用户数据，不恢复SDK连接。出现未知停止状态不强行接管；若其他任务已改变current/配置，停止并重新审阅。

## 验证与审批依据

实现与测试口径见[修复记录](2026-11-02-sdk-clock-fix.md)：141项Python通过；392项公网访问覆盖项经完整运行与单项解释器修正补测完成验证；固定包构建/漂移拒绝7项通过，源码边界审计ready。包只从固定Git源码读取，不混入工作树其他任务相机改动。浏览器本地file预览被安全策略拒绝，未绕过，前端自动化目前是DOM/模拟传输；上线后仍需真实浏览器验收。
此轮只读核对Ubuntu服务均active、NeedDaemonReload=no、SDK断开且readOnly=true。云端预期基线来自上一轮已核验的密码规则发布；应用前须再次全量核对。
需批准范围：上传本固定包、云端2件前端源码、Ubuntu3件校验源码及2件入口drop-in、3个现有服务重启，以及上述不初始化SDK的有界授权验收/回退。具体确认来自已批准[C8方案](2026-11-01-C8-ui-sdk-audit-and-design.md)第9节第6步：“固定源码/资源清单、数据库变更和回退材料完成后才申请实际部署。”本轮不延长租约，不实施完整权限分离。
