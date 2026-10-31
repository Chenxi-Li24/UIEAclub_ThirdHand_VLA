# C1b 具体部署审阅 — 无 SDK 设备网络探针

状态：用户已批准本文件的具体范围，2026-10-30已应用，批准的30分钟探测通过。
实际过程和验收结果见 [C1b变更记录](2026-10-30-C1b-probe-change.md)；
下文保留审批时的候选与基线，不把候选描述当作部署结果。

## 1. 本次范围与验收目标

本次只建立 `Ubuntu → 公网443 → Nginx mTLS → 私有Unix socket → 探针中继`
的认证与心跳链路，用独立PostgreSQL记录一台临时网络探针的公共身份。
持续探测1800秒，分3个成功后主动断开、重新认证的周期，记录RTT分位数和最长心跳间隔。
意外断线直接将本次探测判为失败，不自动重试、重放命令或掩盖中断。

这一步不发布人员注册/登录、历史、相机或控制API，不修改展示站内容，不导入SDK、
Robot Client、CAN、摄像头或媒体库。临时探针无执行实例，控制能力硬编码关闭。
实际机械臂、生产用户数据库与长期设备凭据在后续阶段单独登记和验收。

## 2. 已核实的环境

| 目标 | 当前事实 |
|---|---|
| 云端47.94.95.244 | Ubuntu22.04、x86_64、Python3.10.12；未发现Node/PostgreSQL；系统Nginx提供公网443 |
| 云端资源 | OS可见1608MiB RAM，当前约558MiB使用、867MiB可用；磁盘约29GiB可用；NTP同步 |
| 公网带宽 | ECS固定3Mbps；本次没有视频、原始采样或多观众负载 |
| 学校Ubuntu100.85.63.78 | 默认Python3.8.10；已有独立Python3.11.15解释器；NTP同步，x86_64 |
| 可复用解释器 | `/home/nieqingcao/miniconda3/envs/voice-bridge/bin/python`；只用它创建新venv，不在原环境安装包 |
| 管理与公网路由 | SSH走已验证主机密钥的Tailscale连接；Ubuntu访问云443走校园Wi-Fi出口 |

快照不是持续状态保证。应用前再次检查目标文件、磁盘、可用内存、已有账户/PG集群，
如果期间出现同名服务、数据库或非本任务修改，不覆盖它们。

## 3. 固定发布物

最小云端候选：

```text
文件：.superpowers/sdd/2026-10-30-public-access-rollout/C1b-probe-release.tar.gz
SHA256：0941abb1f0c9ee94afcb4c5cd96d6120c6ede64b5428acf51e48e5b58f27c2a7
大小：181733字节；187个清单文件，外加manifest.json
```

归档仅含探针中继、登记工具、15个纯JS依赖包、五个Python探针模块及本次配置模板。
逐文件SHA256保存在归档内 `manifest.json`；不含密钥、机械臂驱动、业务前端、
Robot Service、测试数据或当前仓库的其他源码。构建器拒绝软链接/Windows junction、
原生Node扩展、未列出的源码及凭据文件。

云端Node使用独立的24.22.1，不替换Ubuntu现有Node或任何系统默认版本：

```text
https://nodejs.org/dist/v24.22.1/node-v24.22.1-linux-x64.tar.xz
SHA256：6c172a9ab6718f7b801fb5a7bd486af2ee5e32758086a04b84fcce2aa77095e6
```

该版本是官方2026-10-21的安全发布，选用它替代本地早期测试的24.19。
见[Node官方发布与校验值](https://nodejs.org/en/blog/release/v24.22.1)。

PostgreSQL使用[官方PGDG Ubuntu仓库](https://www.postgresql.org/download/linux/ubuntu/)
的以下已查询版本，不安装默认 `postgresql` 元包：

| 软件包 | 固定版本 | SHA256 |
|---|---|---|
| postgresql-17 |17.11-1.pgdg22.04+2 |4a3db7ad8ebb016e966d5f1cc390782531f4c111fd234daaf766d18d2be885b4 |
| postgresql-client-17 |17.11-1.pgdg22.04+2 |3719f32e1484b723c225cfb8c2cfdbf31bb56b8593c20c5264bab0376326e22f |
| libpq5客户端库 |18.6-1.pgdg22.04+2 |8af0b458834e219f3aa7c904fa1237ea484950486e3165a3a90204878e060530 |

安装前验证官方APT签名并审阅依赖事务，不执行全系统升级。libpq客户端库版本不代表
安装PostgreSQL18服务器。APT公共依赖清单与版本保存到本次备份清单；固定包不可用、
需要替换现有数据库或移除其他软件时停止应用，先修订差异。

Ubuntu端的纯探针wheel为 `thirdhand_edge_probe-0.1.0-py3-none-any.whl`，SHA256：
`8e1b58e47eb59422c14ca14348c78b74fd4ccd52b9bde9c81480e6efb8958177`。
其五个模块已与候选源码逐字节比对，不含执行/媒体模块。
Linux/Python3.11依赖已从PyPI下载，版本与哈希冻结在
[python-requirements.lock](../../deploy/public-access/probe/python-requirements.lock)。
安装使用 `--no-index --require-hashes --only-binary=:all:` 和本次wheel目录，
不会在学校主机编译或升级现有环境。

## 4. 云端具体配置差异

| 目标 | 本次操作 |
|---|---|
| `/opt/thirdhand-probe/node-v24.22.1/` | 安装校验过的独立Node运行时 |
| `/opt/thirdhand-probe/releases/0941abb1f0c9ee94/` | 解压固定发布物，root拥有；通过 `/opt/thirdhand-probe/current` 选择此版本 |
| OS身份 | 新建禁止交互登录的 `thirdhand-relay`；Nginx socket使用www-data组；另建仅供PG socket的 `thirdhand-probe-db` 组 |
| PostgreSQL17/main新集群 | 新增专用集群，仅Unix socket，禁止TCP监听；不接收校外数据库连接 |
| `thirdhand_probe`数据库 | 只创建 `ops.devices` 和 `ops.device_credentials`，用于网络探针公共证书登记，无人员/执行/采样表 |
| PG角色 `thirdhand-relay` | peer本机认证、最多2连接、只读两张登记表；无写入/建库/建角色/复制/额外角色成员权限 |
| `/run/thirdhand-relay/edge.sock` |0750目录、0660 socket，仅relay所有者和Nginx组可访问；relay进程仅允许AF_UNIX |
| 活动edge Nginx站点 | 替换已备份的 `/etc/nginx/sites-available/edge.uiea-thirdhand.com`，要求临时客户端CA；只转发 `/edge/v1/healthz` 与 `/edge/v1/connect` |
| 主域站点 | 不修改其页面、业务路径或现有HTTP/HTTPS配置 |
| 公网端口/DNS | 继续用现有443，不增加端口或DNS记录，不变更SSH/宝塔权限 |

具体文件：

- [设备入口配置](../../deploy/public-access/nginx/edge-probe.conf.template)。
- [中继服务与资源限制](../../deploy/public-access/systemd/thirdhand-probe-relay.service.template)。
- [探针数据库初始化](../../deploy/public-access/probe/bootstrap.sql)。
- [PG配置](../../deploy/public-access/probe/postgresql.conf.fragment)、[peer认证规则](../../deploy/public-access/probe/pg_hba.conf.fragment)。
- [PG资源限制](../../deploy/public-access/systemd/postgresql-probe-budget.conf.template)。

资源上限拟为：PG384MiB、中继128MiB/Node堆64MiB，PG共享缓冲64MiB、总连接20、
relay池2连接。它们是限制，不能证明所有未来业务服务能同时装入现有主机。
本次只存少量登记数据；C2用户数据、遥测和B6视频仍需独立容量决策。

启动时程序还会查询实际PG角色和授权，拒绝超级用户、额外表读取、任何表写权限、
模式创建或额外角色成员关系；不自动迁移、不创建业务表、不加载签名私钥。
任一证书登记被设置为控制可用时，probe-only进程会拒绝它，而不会升级为控制连接。

## 5. 这次新增的凭据与信任

1. 云端生成独立的**临时网络探针CA**，有效期30天，EC P-256，pathlen0。
   私钥仅存 `/root/.local/share/thirdhand-probe-ca/`，目录0700、私钥0600；不进入发布物、
   浏览器、聊天或Git。仅公开CA证书复制到 `/etc/thirdhand-probe/probe-ca.pem`。
2. 学校Ubuntu以当前已授权的nieqingcao账户，在
   `/home/nieqingcao/.config/thirdhand-probe/` 生成Ed25519私钥和CSR。
   目录0700、私钥0600；私钥不离开Ubuntu。只通过现有SSH通道传输公共CSR/签发证书。
3. 分配一个新的网络探针UUID，签发7天有效、仅clientAuth的证书，SAN为
   `urn:thirdhand:probe:<UUID>`。云端登记工具再次验证CA、有效期、Ed25519、用途和URI，
   写入 `probeOnly=true, remoteControlEnabled=false`；不会覆盖或激活已有/撤销记录。
4. 该UUID代表网络探针，不作为已验证的机械臂硬件身份。以后真机登记使用后续审阅的
   生产CA/身份，不把这张临时凭据升级成控制凭据。

模板：[临时CA](../../deploy/public-access/probe/pki-ca.cnf)、
[客户端扩展](../../deploy/public-access/probe/pki-client.ext.template)。
登记命令仅在本机PostgreSQL管理员身份下运行：

```text
node services/device-relay/src/probe-enroll.js <UUID> <公开设备证书路径> <公开CA证书路径>
```

Ubuntu新建venv位置拟为 `/home/nieqingcao/.local/share/thirdhand-probe/venv`。
创建时使用已确认的Python3.11.15，不更改voice-bridge环境或系统Python；无自动启动服务。
安装纯探针wheel后显式运行：

```text
python -m thirdhand_edge.probe --config /home/nieqingcao/.config/thirdhand-probe/probe.toml --duration-seconds 1800 --cycles 3
```

报告只包含成功/失败、时长、连接次数和延迟统计，不打印证书、私钥、URL或底层异常内容。

## 6. 公共证书续期的实际Nginx重载

安装以下固定目标的root维护单元，只用于两张既有公共服务器证书：

- [service](../../deploy/public-access/systemd/thirdhand-public-tls.service.template)、
  [path](../../deploy/public-access/systemd/thirdhand-public-tls.path.template)、
  [timer](../../deploy/public-access/systemd/thirdhand-public-tls.timer.template)。
- [重载脚本](../../tools/operations/reload_public_tls.py)：验证新公共证书的信任链、名称、
  有效性和私钥权限，运行实际 `/usr/sbin/nginx -t`；证书与当前服务相同时跳过reload。
  只有叶证书变化才重载 `nginx.service`，再检查本机SNI服务实际证书是否匹配。
  失败不会更改站点配置或误报换证完成。

path监视两个公共证书目录；timer每5分钟重试检查，证书未变时不会周期性重载
长连接worker。机制依据[systemd.path官方说明](https://www.freedesktop.org/software/systemd/man/247/systemd.path.html)。
它不签发、更新或信任设备CA，也不会重启Robot Service。
部署时先做单元校验、无变化运行和文件事件触发检查；不会为测试强制申请新的公网证书。
真实续期换证尚未发生，不将模拟测试当作真实CA续期验收。

## 7. 应用顺序与停止条件

1. 创建新的C1b owner-only备份，记录实际Nginx配置、已有软件/单元、APT来源、账户/组、
   资源与C1a证书状态。若目标同名对象已存在或相较C1a有未知修改，先核对，不覆盖。
2. 校验归档及运行时哈希，部署独立目录；准备官方PGDG源及精确包版本，审阅安装依赖。
   阻止新PG集群在默认配置下自动启动，完成本次Unix-only、peer和资源配置后再首次启动。
3. 以本机postgres管理员执行初始化SQL。只读角色经实际连接验证后，才启动中继。
   PostgreSQL和relay都不得出现公网TCP监听。
4. 生成临时CA和Ubuntu CSR，核对CSR签名/UUID，签发并登记公共证书。私钥不通过聊天。
5. 备份后应用edge-probe候选，实际 `/usr/sbin/nginx -t` 成功才reload；主域保持C1a行为。
6. 安装并验证公共证书维护单元；没有证书变化时检查应返回UNCHANGED，不反复reload。
7. Ubuntu独立venv安装冻结wheel，先短探测，再执行1800秒/3周期持续测试。任何意外断线、
   认证失败、资源超限或不明授权，均记录失败并停在此阶段，不进入SDK/相机/真机。

必须获得的实际证据：

| 检查 | 通过条件 |
|---|---|
| 主域 |HTTP/HTTPS仍200，首页SHA256保持C1a值 |
| 无设备证书访问edge |不得获得200健康响应或101连接；允许Nginx客户端证书错误/握手拒绝 |
| 有CA签名但未登记、已过期/已撤销的设备 |无法完成认证；已有连接在重新校验后关闭 |
| 伪造证书头、浏览器Cookie/Origin |无法取得设备连接 |
| 已登记探针 |health成功、WSS101、私钥挑战成功、executorEpoch为null、controlAuthorized始终false |
| 控制/采样/媒体路径 |未发布；即使持有探针证书也不能调用 |
| 持续测试 |累计探测不少于1800秒，3次独立认证，报告RTT p50/p95/p99/max和最长心跳间隔；意外失败不得隐瞒 |
| 现场依赖 |不打开SDK/CAN/相机，不给机器人服务发送命令 |
| 资源与日志 |记录PG/relay RSS与cgroup峰值、磁盘、journal；日志不含凭据；不把本次探针资源值推断为视频容量 |

30分钟测试不覆盖夜间认证或真实网络切换；这些未发生的场景将明确标为未测。
公网控制仍须通过C2/C3及后续媒体与现场停止验收。

## 8. 回滚与保留

失败时先停止本次探针和新relay，恢复备份的C1a edge关闭站点，语法检查通过后reload。
保留主域HTTPS和DNS。停用本次新增的path/timer/service；不切换到宝塔另一套Nginx。

临时登记只做撤销证书/停用设备、角色NOLOGIN；保留审计记录和数据库，不DROP库或删表。
新PG服务可停止并禁用。保留owner-only备份、密钥和发布目录以供追溯，不自动删除，
也不回退到裸9983代理。Ubuntu只结束本次明确PID的探针，不重启现有机械臂进程。

## 9. 审批时的本地验证与限制

- 修补版Node24.22.1上，全部公网模块测试 **114/114通过，0跳过**。
- Python网关测试 **25/25通过**。
- 已验证：专用PG只读角色/最小建表、越权拒绝、短期CA用途/URI绑定、禁止重新激活撤销记录、
  Node↔Python真实mTLS、计时与计划重连、异常不自动重试、无凭据报告、证书重载失败保护。
- 归档内模块与依赖加载成功；Pythonwheel模块集合与源码逐字节一致；归档无链接/密钥/驱动。
- 一次扩展到旧web/Vision的回归为161通过/1失败，失败是既有
  `projected-state-route.test.js` 的 `frame_policy_source_changed`。未修改或绕过源绑定校验；
  只读核对发现其对 `robot-controller.js`、`startouch_bridge.py` 的预期哈希与当前HEAD也不一致，
  因而不是此次C1b探针代码引入的变更。
  本次探针不包含Vision或该策略。整仓通过和真机准入均未宣称。
- 以上为本地隔离测试，尚未进行服务器Linux单元/Nginx实际配置验证或30分钟校园实测。
  批准后按上面的实际验收点执行；不能提前把C1b标为部署完成。
