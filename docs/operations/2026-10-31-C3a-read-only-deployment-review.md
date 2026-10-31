# C3a：外网 SDK 只读连接与真实数据入库部署审阅

当前状态：**用户已批准并实施只读部署；已取得 685 条真实六轴样本，管理员账户/历史查询和观察员权限检查通过。实时入库延迟、连续连接和当前相机稳定性未通过。** 详见 [实际实施及复核报告](2026-10-31-C3a-read-only-change.md)。

以下保留审批时的配置、发布物和预检快照，涉及“尚未部署”的文字均描述审批前状态，不代表当前运行状态。最终发布目录为 `/opt/thirdhand-stage/releases/f2c14f11d88c289e`。

用户最新现场条件：现在无人，只连接、读取状态并准备系统。本次不执行运动、夹爪、Home/Zero、固定点或动作序列；Three.js 模拟仍可独立操作。完整真机运动权限继续关闭。

## 审批范围

| 位置 | 具体变更 | 目的与影响 |
|---|---|---|
| `staging.uiea-thirdhand.com` | 切换独立业务发布物；新增 `/stream/v1/control` 的精确 HTTPS/WSS 反代 | 现有管理员账号 + MFA + CSRF + 当前会话才能申请单人 SDK 连接权；登录本身不连接 SDK |
| `edge.uiea-thirdhand.com` | 保留现有严格 mTLS 与相机路由；新增 `/edge/v1/telemetry-batches` 精确路由，单次请求上限 360 KiB | 设备签名上传；提交入库后才 ACK；现有 connect/media-grant 的超时和 16 KiB 限制不扩大 |
| 云端 Nginx 证书分流 | 仅新增 `CN=thirdhand-stage-sdk-readonly-20261031` 到已有 staging Unix socket | 相机和机械臂分别使用设备 ID、证书与连接，互不顶掉 |
| PostgreSQL `thirdhand_stage` | 正向迁移 `009-scoped-device-control.sql`，增加凭据级控制开关和只读模式；现有凭据默认无 SDK 权限 | 相机/探针证书不能因设备标记改变而自动升级为控制凭据 |
| PostgreSQL 运行身份 `thirdhand-stage` | 应用 [精确授权 SQL](../../deploy/public-access/staging/device/runtime-grants.sql) | 只增加采集、操作日志和控制权所需写入；不增加 DELETE、DDL、设备启用或凭据登记权限；数据库仍仅 Unix socket |
| 设备授权 | 登记只读设备 `ee625a57-049a-4c5d-92e1-9578ab9d21c3`、凭据 `5d782909-cdce-4939-83b2-9ec76667e9dd`，签发 7 天客户端证书 | 仅允许显式 connect/disconnect；云端服务、中继、Ubuntu 本地均拒绝运动命令 |
| 云端配置 | 新增 `DEVICE_TELEMETRY_ENABLED=1`、`DEVICE_CONTROL_ENABLED=1`、独立 Ed25519 控制签名密钥配置 | 复用已有私有 socket；密钥与相机签名、账号 CSRF/MFA 密钥独立；私钥不入 Git/网页/聊天 |
| Ubuntu `100.85.63.78` | 使用独立目录 `/home/nieqingcao/.local/share/thirdhand-stage-device/20261031`，原 Robot 服务增加可撤回 drop-in，启动独立 Agent 用户服务 | 原仓库未提交代码保留。适配器只包装现有现场代码，不覆盖原工作目录 |
| Ubuntu 原服务入口 | 新入口硬编码只读，保留原来的 SDK/Python/CAN/速度/URDF/ready-file 绝对路径；明确 `NODE_PATH` 指向原有依赖 | 原 9983/本地旧 WebSocket 的 SDK 直连路径在接入期间返回拒绝，避免绕过；模型展示不属于真机连接 |
| 网页 | 管理员账户页扩展注册信息；控制面板显示最新入库六轴状态；历史页按设备名称查询 | 管理员可查看用户名、姓名、邮箱、组织、角色、状态、注册/验证时间。密码、哈希、验证器密钥、恢复码不会显示 |

不增加公网端口，不修改展示站，不录制视频，不删除历史数据，不创建额外的人类管理员账号，不修改用户密码或 MFA。

## 精确文件

- 云端环境：`/etc/thirdhand-stage/cloud.env`。
- 云端站点：`/etc/nginx/sites-available/staging.uiea-thirdhand.com`、`/etc/nginx/sites-available/edge.uiea-thirdhand.com`。
- 证书分流：`/etc/nginx/conf.d/thirdhand-stage-media-routing.conf`。
- 模板：[控制 WSS](../../deploy/public-access/staging/device/control-location.conf)、[数据上传](../../deploy/public-access/staging/device/telemetry-location.conf)。
- Ubuntu 原用户服务：`thirdhand-tcp-calibration-robot.service`，保留 `90-main-directory-step1.conf` 与 `95-meituan-speed20.conf`，新增 [99-read-only-sdk.conf](../../deploy/public-access/staging/device/99-read-only-sdk.conf)。
- Ubuntu 新用户服务：[thirdhand-stage-edge-read-only.service](../../deploy/public-access/staging/device/thirdhand-stage-edge-read-only.service)。
- 云端应用工具：[staging_read_only_sdk.py](../../tools/operations/staging_read_only_sdk.py)，默认只审阅，`--apply` 才实施；Ubuntu 快照工具：[build_robot_read_only_release.py](../../tools/deploy/build_robot_read_only_release.py)。

独立 Robot 快照保留 14 个现场源文件；只包装原 `server.js` 和 `config.js`，另加入签名/控制策略模块。SDK 源码、生成模块、Python、Node 依赖与原配置保持实际绝对路径绑定，安装前再次核对。不由 Agent 导入 SDK 或直接访问 CAN。

## 已准备、尚未启用的发布物

| 发布物 | SHA-256 |
|---|---|
| 云端完整包，4,622 个文件 | `325d182fe15199d5423ff918a88f3f2fadd810da0aa65a3e97c87183639d3d5d` |
| 云端 manifest | `1fbab3ec302318f18764566e5b1d0bf559764abbbbfa8b6cb86a93d2e6b53b1a` |
| 独立 Robot 只读快照，19 个文件 | `b250c684d8dcd3a878858ab893761302a99342b053a21471ab5851e227e39377` |
| 云端审阅/运维包 | `e333168ff899e2e5069ac8d9e96f0e7f97456714287f5c2cf0dbabb4addbd61c` |
| Agent 源码包（不含 SDK、凭据或数据） | `5d093cd7e4a6f65afbf056f026d1d50b8522d06af020cf04a7b3c6c3d1328895` |
| 设备公开 CSR | `ee77990195a345fec3825c71fdd1da9d5a181f1870069e52f5cf5f6e898b999d` |

当前云端版本仍是 `fecd12218feca574`。新云端候选目录为 `/opt/thirdhand-stage/releases/325d182fe15199d54`。Ubuntu 仅准备了未获签 CSR，私钥留在其私有目录，尚无新增设备访问权限。

## 执行与验收

1. 验证包、清单、CSR、现有源码与当前配置哈希；备份云端配置、数据库及 Ubuntu 服务配置。任何原文件变化先停止应用并复核差异。
2. 正向迁移、精确授权、签发与登记只读凭据，配置相应 Nginx 路由，切换 staging。API 和现有视频观看会短暂重连；原相机发布服务自行重连，网页可能需要再次点击 Watch camera。
3. Ubuntu 保留原运行路径和现场改动，安装只读适配器与独立采集/上传/控制进程。启动后先证明 **SDK 仍未连接**、相机可用、旧 SDK WebSocket 旁路拒绝。
4. 用户以现有管理员账号完成正常登录/MFA；从网页显式申请连接权、点击 Connect SDK。本轮仅短时读取六个关节状态，随后 Disconnect SDK。若连接或断开结果不确定，停止验收并保留“未确认”，不反复自动连接。
5. 对照源序号、六轴值、原始状态与数据库已提交记录，验证真实采样、操作/连接事件、原始批次可查询；未知电流/TCP/校准字段保持未知，不用零值或模拟值填充。
6. 管理员网页验收注册账户与真实记录。观察员可读取完整运行记录、观看相机和操作模型，直接请求 SDK/管理员账户接口仍被拒绝。相机选择器只列相机，SDK 选择器只列可连接设备。
7. 验证结束后 SDK 断开；报告真实样本数量、源模式、时间区间、入库延迟/积压和运动指令数（应为 0），再交用户复核。无人条件下不进行真机故障注入、急停或运动验收。

连接和断开分别形成操作记录；采样按设备、启动号、源序号和时间追溯。已上传原始批次保留精确内容。并非所有硬件字段都有真实来源，缺失字段明确标识。没有执行的运动不创建“成功运行”记录。

网页最新状态用于展示，不作为运动控制的实时反馈依据。丢失浏览器授权/当前控制连接后，本地只读适配器排队断开 SDK，并等待断开回执；`READ_ONLY_SDK_DISCONNECTED` 只表示 SDK 连接释放，不表示已验证物理停止能力。设备启动、重连和历史回放均不自动 connect SDK。

## 备份与回退

云端审阅目录为 `/var/backups/thirdhand/access-C3a-sdk-readonly-20261031`。应用前保存四个活动配置及完整数据库备份；旧发布物保留。失败时独立尝试撤销新增设备、恢复原配置、恢复旧发布指针并重启服务，数据库失联也不能跳过文件/程序回退；未完成步骤写入 `rollback-result.json`。

Ubuntu 先断开 SDK 并确认结果，再停止新 Agent、撤回新增 drop-in、恢复原用户服务；不覆盖/清理原仓库。断开未确认时保持新连接关闭并报告，不把杀进程当作物理停止证明。

数据库迁移只前滚，已收集数据不删除、不回放任何未决命令。新增写入授权在维护回退后复核/撤回；数据库不可用时保留待办，不能谎报已撤销。原相机凭据与服务不撤销。

## 验证与未完成项

本地 Node 24.22.1 + 隔离真实 PostgreSQL：**143/143 通过、0 跳过**；独立设备端与部署回退 Python：**39/39 通过**。最小权限入库、延迟连接期间撤销、凭据不自动升级、只读运动拒绝、数据库故障回退、版本元数据均有回归。

一次独立复核的 4 项问题均已先复现失败再修复：待连接被误判断开、凭据行锁导致写入失败、数据库故障阻断回退、采样版本字段丢失。本次不宣称全仓库测试通过；已有无关依赖/平台测试基线保留。

尚未完成：本次实际部署、外网网页 SDK 连接、真实样本入库与网页验收；全功能运动、可靠物理绑定/停止证据、视频采集时间戳、队友教程合并、长时间容量和正式公网发布仍在后续阶段。

这次审批仅对上述只读接入和查询部署生效。已批准计划要求“所有实际配置在实施前先展示确切目标、配置差异、备份与回退”；浏览器操作规则也要求在新增安全敏感设备访问前确认。因此先提交这一组具体配置，批准后实施，无需重复批准其中的普通检查步骤。

补充实际预检：云端只审阅模式已验证 4,622 个候选文件、25 项差异，四个活动配置哈希保持一致，当前 API 仍报告设备控制未启用。Ubuntu 已核对两个待安装包和现场原源码哈希，在实际运行时完成 13 个 JS、25 个 Python 文件语法检查；SDK 仍断开，服务变更和运动指令均为 0。审批请求已发出，尚未应用以上变更。
