# C3c 第一批部署候选：仅修复连接、媒体授权与上传

状态：**云端一文件修复已于21:26:28应用；Ubuntu 两个传输服务已于21:53应用并复核。** 实际执行见 [C3c记录](2026-10-31-C3c-transport-change.md)。本批不开放运动，不部署本轮 Robot/停止/限位/运动准入代码。本候选构建器没有部署能力；应用器独立接受范围/回退审阅和即时预检。

对应 [外网运动修复计划](../superpowers/plans/2026-10-31-remote-motion-readiness.md) 的连接、媒体和只读上传部分。用户已批准按计划实施；本文件把第一批实际差异固定为可审阅对象。

## 1. 固定范围

| 位置 | 运行源码变化 | 应用方式 |
|---|---|---|
| 云端 | 仅 `services/cloud-api/src/control/websocket.js` | 从当前 C5 发布复制独立新目录，只覆盖此文件和 manifest，校验后切换 current，重启 `thirdhand-stage.service` |
| Ubuntu Agent | 仅 `thirdhand_edge/media_upload.py`、`media_publisher.py`、`upload.py`、`runtime.py` | 从已核验旧来源构建新的 20 模块快照；user edge 单元新增仅含 PYTHONPATH 的 drop-in，指向新目录 |
| Ubuntu 相机发布 | 仅 `thirdhand_edge/media_upload.py`、`media_publisher.py`、`camera_runtime.py` | 新的 20 模块相机快照；仅 system camera-publisher 单元新增 PYTHONPATH drop-in |

相机源进程、Robot/Vision/Web 服务、Ubuntu 原仓库、SDK 二进制、CAN、设备限位、运动能力、数据库结构/权限、mTLS 凭据、SMTP、Nginx 路由和公网端口均不在此批变更中。独立 private 配置和状态/outbox 目录继续使用原位置；不复制或输出私有文件。

## 2. 修复内容与实际效果边界

- 云端 WebSocket 之前把“身份异步校验期间到来的第二条合法挑战响应”当作协议错误。新实现只允许一条处理中、一条等待，仍逐条验证当前会话和原始 500 ms 挑战有效期；关闭/正在关闭的 socket 不能获得 fresh ACK。
- 媒体续期根据当前仍有效租约的剩余时间调度，避免固定等待 200 ms 后才开始请求。原 600 ms HTTP 读超时、950 ms 签名有效期和 50 ms 单调监控不放宽；失败/过期 Gate 不能再被晚到响应复活。
- 新媒体时序诊断只允许固定阶段和数值，不包含请求体、JWT、Cookie、私钥、认证头或任意异常文本。
- 遥测上传复用已验证 mTLS 连接，以紧凑 JSON 序列化不可变批次，并在积压仍存在时继续处理后续有界批次；保留每批哈希、事务确认和失败不重放动作规则。不使用 gzip 或改变旧服务端上传协议，不修改原始采样率或删除历史。

这些本地缺陷的修复**不等于真实校园网络所有响应头超时已经消失**。部署后仍须重新观察两路观看、持续只读状态和故障恢复。没有通过实测时保持只读，不能因修改了调度就开放运动。

## 3. 已核验的旧版本

| 项目 | 固定值 |
|---|---|
| 云端 current | `/opt/thirdhand-stage/releases/6187bbbe8ec4d5e8` |
| 云端 manifest SHA-256 | `e6d791d66ca8ad1f59a85e076df5de360cea6ec9ce746643caaf9507baf55ba4` |
| 云端旧 websocket.js SHA-256 | `2535fc00058bd29a2c32489535cf096e9126d19683840d2f31e506d789db01a4` |
| Ubuntu Agent 旧目录 | `/home/nieqingcao/.local/share/thirdhand-stage-device/20261031/agent-source` |
| 相机旧目录 | `/home/nieqingcao/.local/share/thirdhand-stage-camera/20261031/source-e9c8e33a97903125` |
| 相机旧 manifest SHA-256 | `e9c8e33a97903125809ea107571ab9a4abeb003abc293c36846c09dd3ce4edc4` |

主任务通过已验证 SSH 于北京时间 **21:02:33** 核对 Ubuntu 两个目录各 20 个 Python 模块、单元实际 FragmentPath/PYTHONPATH；两个目标单元当时均没有 drop-in，SDK=false、设备仍 readOnly。Agent NRestarts=7、相机 publisher=891，反映旧版的不稳定状态，不能当作候选发布后的重启计数。

云端经已登录宝塔终端实际核对 current、manifest、websocket 文件摘要全部与上述值一致，requested/active/revoking 租约数量为 0。两份不含秘密的实际核验记录已随包保存：`remote-before-public.json`、`cloud-before-public.json`。这些是检查时的快照，**不能代替应用时再次确认 SDK 断开、无活动控制权及当前服务状态**。

### Agent 旧包与最终安装记录的差异

C3a 初始 tar 中 `capture.py`、`runtime.py` 在后续现场排障后与最终安装内容不同。打包器以 `C3a-ubuntu-installed-final-public.json` 的最终公开文件摘要为权威基线，且与 21:02 的实际 Ubuntu 哈希逐项一致。

本批保持 `capture.py` 未改：从本地取得恰好符合最终安装摘要的字节。`runtime.py` 是本批允许替换的文件，本地没有其最终旧字节，因此不以旧 tar 伪造文本 diff；`changed-files.json` 保存实际旧摘要与新摘要，部署器必须对照实际旧目录验证。其他未批准文件不从当前开发目录带入快照。

## 4. 冻结候选与摘要

候选目录：

```text
D:/claudeworkplace/thirdhand-login/.superpowers/sdd/2026-10-31-remote-motion-readiness/transport-candidate-0a727ed3a6caa651
```

整体候选标识 `0a727ed3a6caa651f1a89144f16d94fea8964d3527af0714373223fbe9d37fb8`，覆盖候选清单、基线核验及制品摘要。精确的每个文件旧/新 SHA 位于 `changed-files.json`，完整 20+20 源清单与原发布信息位于 `baseline-public.json`、两个源码包内的 `source-manifest.json`。

| 制品 | 大小 | SHA-256 |
|---|---:|---|
| cloud.delta.json.gz | 279192 B | `2ed1012f84bcd467c5b02ba67c921cd7e134ddceec851b82d5867eea5edc20ca` |
| agent.source.tar.gz | 30467 B | `a1c72c502734b8d4288952240b2c8018a6efd2ad3c59e80c771f2a14769c649e` |
| camera.source.tar.gz | 29173 B | `53304aa81891fcd922706cb80bb21288099cf842a3ca44ce460125089e3d8817` |
| changed-files.json | 1698 B | `978a21968f678d6f1cf41fad309fef636fb7dfb59ac5be06e4c15e5e84ea73ed` |

新位置：

- 云端 `/opt/thirdhand-stage/releases/04cc19054caa45a6`；新 manifest SHA 为 `04cc19054caa45a6406450ac058caf76935be4d51e0590499d28bac5a2fa4917`。此目录标识由新 manifest 摘要产生，不冒称完整 tar 的摘要。
- Agent `/home/nieqingcao/.local/share/thirdhand-stage-device/20261031/agent-source-aef304c8c1efc5de`。
- 相机 `/home/nieqingcao/.local/share/thirdhand-stage-camera/20261031/source-5bf518471ff7aa60`。

旧快照不修改。候选内两个 `.conf.template` 只有 PYTHONPATH 赋值，不携带认证配置或替换完整单元。

## 5. 构建与核验方式

新增 `tools/operations/prepare_motion_transport_fix.py`，SHA-256 为 `0aa61d32ea832b763168df69f43d61c0904c86336974a4bfa9dc61f8577ae0fe`。

```powershell
# 默认只读审阅：不创建输出目录，不修改服务。
python tools/operations/prepare_motion_transport_fix.py

# 仅在本地写出不可变候选，不连接任何主机。
python tools/operations/prepare_motion_transport_fix.py --build
```

构建器固定验证 C5 delta、C3a 初始 tar/最终 receipt、C2i 公开嵌入包的 SHA；历史相机部署脚本仅用 AST 读取 base64 常量，绝不执行。源码在同一构建中只读取一次，保证 Agent/相机共用模块字节相同。相同输出可重复校验，已有候选的内容不同则拒绝覆盖。

构建器的 `--apply` 被拒绝；它不是安装器。Ubuntu 安装器见下一节；云端安装器由主任务独立准备。不能把本文件的步骤视为已执行脚本。

### Ubuntu 应用器（已本地验证，未远端执行）

`tools/operations/apply_motion_transport_ubuntu.py` SHA-256：

```text
05ccb3e2e32614259bf7af92ee6afaa73e3205056e54c28761ea409a9a10e375
```

固定输入位置为 Ubuntu `.../thirdhand-stage-device/20261031/incoming/transport-candidate-0a727ed3a6caa651`。脚本以 **nieqingcao / UID1000、Python≥3.11** 运行，不接受任意目标目录或单元名称；只消费本候选固定 SHA 的两个源码包、公开基线和两个 PYTHONPATH 模板。

主任务已通过 SSH 额外核验并固定原主单元 SHA，应用器在 review/apply/rollback 均复核，不仅比较 PYTHONPATH：

- user edge 单元：`fbfcc732e86ecee25d2ec98e802f6735fc5701b226d2ee58b810998c78898dd7`。
- system camera-publisher 单元：`c604a65a072f9cc83d1ebe0d08c72f8f95c7faf12148fd64f99c2c0dc0c42e51`。

默认运行只检查、输出公开 JSON，不创建备份或新目录。固定读取原 `private/edge.token`，只在本机内存用于回环 GET；不会打印、复制或更改令牌。Robot 的 SDK/readOnly 和健康状态不可确认时停止。

review/apply/rollback 除检查已加载的 DropInPaths 外，也枚举两个固定 drop-in 目录中所有磁盘 `*.conf`；发现尚未 daemon-reload 的未知文件、符号链接或本次文件字节变化即拒绝。切换期间在每次配置变更、重载/重启前继续复核，防止中途出现外部配置后仍继续应用。

显式 `--apply` 还需一份**应用当时**由主任务核验的公开云端小记录，通过 `--cloud-review-file` 与 `--cloud-review-sha256` 一起传入。旧候选 before 快照不能代替此记录。格式为：

```json
{
  "verified": true,
  "currentRelease": "/opt/thirdhand-stage/releases/04cc19054caa45a6",
  "deviceId": "ee625a57-049a-4c5d-92e1-9578ab9d21c3",
  "activeLeases": 0,
  "checkedAt": "本次实际核验的带时区ISO时间"
}
```

计数包括 requested/active/revoking。文件由 UID1000 持有、权限0600，不是符号链接；SHA 必须等于本次显式参数。记录最多60秒、未来误差最多5秒，只用于本次维护前置检查，**不延长任何设备或媒体租约**。主任务须保证切换期间不再申请控制权；公开记录不是跨主机事务锁。

应用器固定新增：

- `~/.config/systemd/user/thirdhand-stage-edge-read-only.service.d/50-C3c-transport.conf`。
- `/etc/systemd/system/thirdhand-stage-camera-publisher.service.d/50-C3c-transport.conf`，通过 sudo install 固定文件实现。

新目录仅包含20个模块及 manifest，路径穿越、链接、重复项和越界文件均拒绝；源码只做编译检查、不执行导入。源码目录/文件随后设为仅拥有者可读/遍历、不可写，避免运行时缓存改变冻结目录。应用前后复核原主单元和全部新旧源码摘要，仅重启两个限定单元。

固定备份位置为 `.../thirdhand-stage-device/20261031/transport-review-0a727ed3a6caa651/`，保存 `before-public.json`（原 drop-in 不存在、主单元摘要）和经过固定 SHA 校验的公开 `baseline-public.json`；不复制私人配置。

失败且本机 SDK/云端维护前置仍可确认时，自动撤回本次字节完全匹配的 drop-in，重载/重启相应单元。SDK 状态变化或未知、主单元/其他 drop-in 变化、旧源码损坏时返回 `rollback=blocked`，停止进一步变更，交由主任务处理；不杀进程来声称安全。

显式 `--rollback` 使用本机备份的固定旧源码基线，**不依赖 incoming 候选或损坏的新源码**。即使上次在撤回文件后崩溃、systemd 仍缓存新路径，也会完成限定的重载/重启。回退允许云端已经恢复到原 C5 发布，但仍需新的60秒维护记录、SDK断开和无活动租约。

显式 rollback 与 apply 取得同一安装锁；锁被占用时返回 `INSTALLER_BUSY`，不撤回文件或重启服务。apply 失败时的内部回退沿用已持有的锁，避免嵌套取锁。

回退在每个文件撤回前、每次 daemon-reload 前、实际 restart 前以及最终成功报告前重复核验同一份云端记录和本机 SDK 状态；记录过期即返回 `CLOUD_REVIEW_STALE`、`rollback=blocked`，保留已经恢复的部分，待主任务提供新的真实核验记录再继续。重新执行时对两个固定单元完成重载/重启，因为仅见到 systemd 配置指向旧 PYTHONPATH，不能证明上次中断前的实际进程已完成重启。新旧源码、历史状态和 outbox 均保留。

示例（仅说明参数，未执行）：

```bash
/home/nieqingcao/.local/share/thirdhand-media-acceptance/20261031/venv/bin/python apply_motion_transport_ubuntu.py
# 核验本次公开云端记录后才添加 --apply，或在回退时用 --rollback：
/home/nieqingcao/.local/share/thirdhand-media-acceptance/20261031/venv/bin/python apply_motion_transport_ubuntu.py \
  --apply --cloud-review-file /absolute/path/to/fresh-cloud-review.json \
  --cloud-review-sha256 <该文件本次实际SHA256>
```

## 6. 应用器必须执行的即时检查与备份

1. 复核云端 current 及全部旧 manifest 文件哈希，Ubuntu 旧目录 20+20 哈希、实际单位路径与空 DropInPaths，确认未出现新的现场修改。
2. 确认 SDK=false、机械臂无运动、没有 requested/active/revoking 控制权；若状态未知或新租约出现，在任何切换前停止应用。这里只读取状态，不用自动连接/停止动作来制造通过条件。
3. 云端建立 root-only 备份目录，例如 `/var/backups/thirdhand/access-C3c-transport-20261031`；保存旧 current 指向、相关单元公开配置摘要和候选清单。私有配置只在原机必要备份，不下载到本地、不打印内容。
4. Ubuntu 建立独立 user-owned 审阅/备份目录，保存 edge 与 publisher 的实际单元/已有 drop-in 状态及原 PYTHONPATH；从不存在的 drop-in 状态生成可撤回文件，不覆盖主单元。
5. 记录原配置、独立 private 配置和状态目录的存在/权限及摘要，后续确认没有变更；不把私有文件纳入源码包。备份不能成为读取/输出认证内容的理由。

## 7. 分批应用与即时回退

1. 云端复制已核验 C5 到新发布，覆盖唯一允许的 websocket 模块和 manifest，校验完整新清单，再原子切换 current、重启业务 API。保留 export-worker 与数据库配置；失败恢复旧 current 并重启同一服务。
2. Ubuntu 解包到上述不存在的新目录，拒绝路径穿越、重复条目、符号链接及非普通文件，核对每个文件哈希并做模块编译检查；禁止原地覆盖旧源码。
3. 用已核验 user edge 单元的新增 drop-in 切换 PYTHONPATH，daemon-reload 后仅重启 `thirdhand-stage-edge-read-only.service`。Robot 不重启，SDK 不自动连接；新 Agent 建立新 boot/connection，不继承旧租约或重放动作，outbox 目录保留。
4. 用系统 camera-publisher 的独立 drop-in 切换 PYTHONPATH，daemon-reload 后仅重启 `thirdhand-stage-camera-publisher.service`。不切换 camera-source 的 PYTHONPATH，不重启原 Vision/Robot/Web。
5. 逐步检查摘要、服务健康、设备只读/SDK=false、相机源序号推进、publisher 状态与失败计数；任一步失败，撤回本批新 drop-in、恢复原指向并重启对应服务。

回退前仍须确认 SDK 断开且没有新的控制权，状态不明不得恢复旧裸控制入口或把重启当作物理停止。历史/outbox 不删除，未确认命令不重发；候选、失败报告及原源码留存便于复核。

## 8. 部署后的独立验收

- 正常用户会话/MFA 下验证真实控制连接续期；需要 SDK 连接的只读采集单独按已授权流程进行，不由安装器触发。默认启动后保持 SDK 断开。
- 两路真实观看与只读状态并发连续观察 30 分钟，记录新基准 PID/重启计数、控制/媒体延迟、自然失败、数据积压与原始采样完整性。
- 在获准范围复测 35 秒相机撤销/恢复故障，自动恢复规则独立于测试进程；检查失败关闭和恢复后的重新授权，不用旧版通过记录替代。
- 如果实际网络仍超过预算，报告本轮未通过并继续只读排障；不修改租约/状态时限，不扩大本批范围。

## 9. 本地证据与尚待完成

打包器自包含合成公开基线测试 **7/7**，加既有 staging/只读部署专项共 **10/10**、无跳过。测试覆盖精确 1/4/3 文件范围、最终 receipt 优先、摘要篡改、SDK/单元状态不符、默认不写、不提供 apply、候选确定性与拒绝覆盖，以及构建时共用源码一致性。真实 C5/C3a/C2i 与本轮云/Ubuntu 检查记录另做了固定摘要构建核验；合成测试不冒充实际部署验收。

Ubuntu 应用器另有 **34/34** 自包含测试，包含仅审阅无写、即时云端记录缺失时零写入、固定源/主单元漂移、坏 tar、受限 apply、失败自动回退、SDK状态变化时停止、并发安装幂等、未知文件/已加载 drop-in 保留、候选/新源码损坏仍可回退以及旧源码损坏拒绝回退。本次独立审阅修复补充显式回退锁冲突、撤回/reload/restart/等待完成各阶段云记录过期后暂停及新记录恢复、已加载配置显示旧路径时仍完成进程恢复、磁盘未加载 foreign.conf/符号链接阻断三个入口、中途出现外部配置停止后续重启的测试。连同打包与旧部署专项共 **44/44** 通过，无跳过；未依赖忽略目录中的真实备份作为 CI 测试夹具。真实冻结包额外本地加载、编译检查通过，未执行系统命令或访问网络。

本次还尝试项目默认 `python -m pytest -q`：因该本地测试环境缺 PyYAML/cv2，及既有 speech/edge 同名 `test_runtime` 导入冲突，9 个文件在收集阶段报错，未宣称项目全套通过。完整名单见本计划证据 `ubuntu-review-project.txt`，本修复不修改这些无关依赖或测试。

尚待主任务完成：Ubuntu 应用器最终复核、即时预检及应用、30 分钟稳定观察与故障复测。云端已应用状态与上传进展以本文件顶部和实际变更记录为准。上述应用器修复与测试均仅在本地完成，未远端执行；没有 Git commit/push。
