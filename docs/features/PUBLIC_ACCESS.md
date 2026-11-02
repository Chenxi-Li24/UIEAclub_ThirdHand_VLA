# 公网工作台：实现、资源和运行说明

本说明对应2026-11-01的login分支实现。展示站为`uiea-thirdhand.com`；登录/控制业务目前在`staging.uiea-thirdhand.com`，当前云端已部署C8，设备部分已回退、修正候选待应用。实际状态以[C8部署记录](../operations/2026-11-01-C8-deployment-change.md)为准。代码具备的接口不等于真机运动已获准。

## 组成和数据流

| 模块 | 职责与入口 |
|---|---|
| `showcase/` | 独立React/TypeScript/Vite展示站；首页、桌面导航和移动菜单跳转现有登录页 |
| `apps/web/public` | 独立登录/注册/邮件验证/重置页；受保护的Three.js工作台和历史查询页 |
| `services/cloud-api` | Node24业务API、同源鉴权、账户/MFA、点位、历史、媒体授权、设备控制门禁 |
| `platform/identity` | 密码摘要、短期邮件令牌、会话/CSRF、角色/模式、MFA、限流、SMTP |
| `platform/storage` | PostgreSQL迁移、账户/审批、审计、设备租约、真实遥测、导出和个人点位 |
| `services/device-relay` | 云端设备注册和消息通道；mTLS接入后按设备/能力处理消息 |
| `services/edge-agent` | Ubuntu主动建立云连接；本地有界journal/outbox、遥测上传、视频发布及租约约束 |
| `services/robot` | 本地SDK适配及独立工作进程/软件租约取消；物理停止能力另行验收 |

浏览器通过HTTPS访问Nginx，再访问仅loopback监听的业务API；数据库在私有Unix socket上，浏览器不能直连数据库。Ubuntu从学校网络主动连接设备网关，服务器不需要向校园网发起入站连接或做校园路由器端口映射。校园网仍须允许DNS、出站TLS/WSS和选定媒体传输；能连Tailscale不代表公网443或视频媒体链路一定正常。Tailscale只作为维护通道，不代替业务鉴权。

Three.js模型在浏览器本地运行。模型点位保存走业务API/PostgreSQL，回放留在浏览器。真实设备路径为“管理员会话→控制权/连接绑定→签名命令→云端中继→Ubuntu校验→本地SDK”；遥测反向经过本地outbox和云端校验后入库。相机为Ubuntu发布至私有媒体服务，浏览器先取得短期观看授权，再接收视频；账户退出/撤销与媒体授权撤销关联。

## 登录、角色与账户管理

一人注册一个账户，登录时选择Observer或Administrator，默认Observer；角色由服务器保存，页面选择不能提权。管理员角色可进入观察员模式；管理员模式还要求验证器或有效恢复码。观察员可以多账户/多端观看和模拟、查看完整运行记录；不能连接SDK、发真实指令或语音控制。

管理员身份会话和设备独占控制权是两层概念。租约绑定用户、会话、浏览器实例、连接和设备；另一管理员申请接管通过显式的请求/确认流程，不把普通登录自动当成真机控制。当前真机仅已验收连接/读状态，运动门禁关闭。

开放注册由`REGISTRATION_MODE=open`启用，仍需邮件验证、密码规则和限流。账户邮箱不区分大小写。首批管理员使用维护CLI导入私有一次性名单；名单不进入Git，已撤销管理员不会因重新登录再次领取。其他账户在个人设置申请，另一位管理员用密码及新鲜MFA证明审批；不能自批，结果留审计，提权后撤销旧会话并重新登录。

关键接口：

| 接口 | 作用 |
|---|---|
| POST `/api/v1/auth/register`、`/api/v1/auth/login` | 注册/按请求模式登录；服务器验证后签发Secure会话Cookie |
| POST `/api/v1/auth/verify-email` | 消耗一次性验证令牌；成功提示后跳登录 |
| POST `/api/v1/auth/forgot-password`、`/api/v1/auth/reset-password` | 请求重置邮件/消耗重置令牌；真实收件人重置流程仍待验收 |
| GET `/api/v1/session`、POST `/api/v1/session/logout` | 身份与模式读取、退出/撤销 |
| GET/POST `/api/v1/me/profile` | 读取/保存自身资料；邮箱修改不是普通资料字段 |
| GET `/api/v1/admin/users`、`/api/v1/admin/users/export` | 管理员成员表与CSV；普通Observer拒绝访问 |

业务API复用同源检查、会话、CSRF和动作授权。密码/邮箱令牌/MFA秘密不写入日志、URL查询参数或Git；邮件链接使用fragment。密码输入实时显示未满足要求，页面底部列规则。验证器二维码在本地生成，不调用外部二维码服务；两步验证按密码→验证码分步显示，已不需要密码的步骤不保留密码框。

## 个人模型点位（C6）

手动控制页“我的点位”允许命名保存当前六轴模型角度和夹爪开度，刷新或重新登录后从服务器读取，一键约800ms插值调用。可停止，删除需要页面内确认。名称最多120字符，每账户最多100项。模型未加载或播放中不能保存；无效/损坏/版本不符点位显示不可用。英文默认，随既有中文偏好同步，点位名称不被翻译。

前端`model-waypoints.js`只依赖session client、arm model和`simulation-controller.js`，不引用SDK或真机传输。UI反映完成/停止/失败，夹爪与六轴在同一插值循环更新。网络操作等待最多10秒；保存/删除超时表示“结果未确认”，须刷新核对，不自动重试，迟到响应不会覆盖新的状态。

| 接口 | 参数与行为 |
|---|---|
| GET `/api/v1/me/waypoints` | 当前principal的个人列表及上限 |
| POST `/api/v1/me/waypoints` | `{name,joints:[六个有限数字],gripper:0..1}`创建 |
| POST `/api/v1/me/waypoints/delete` | `{id}`，SQL同时限定本人user_id；不存在/非本人统一404 |

服务端模块为`platform/storage/src/model-waypoints.js`、`services/cloud-api/src/routes/waypoints.js`。复用已有`simulation.user_programs`，**无新增迁移**；本次仅授予业务角色schema.USAGE及该表SELECT/INSERT/DELETE。创建时锁定账户行后检查配额，防止并发超过100。

保存的JSON为`{kind:'model_waypoint',version:1,source:'model',unit:'deg',joints:[...],gripper:0..1}`，`model_version=startouch-v3-model-v1`。user_id、source和版本由服务器决定，客户端不能伪造硬件来源。模型角度范围分别为[-162,162]、[-12,201]、[-183,0]、[-98,98]、[-98,98]、[-164,164]；它们不是已核实的真机机械限位。

调用不建立控制租约、不连接SDK。第一版不含复杂多步编排、共享点位或真机实测点位，也未把模型播放结果写成完整执行历史。真实验收已覆盖保存、刷新、两个模式调用、用户退出后新Observer登录读取和调用，数据库确认1条真实模型点位且模型验收期间零真机命令。

## PostgreSQL、运行记录和媒体

迁移位于`platform/storage/migrations`，001–010依次引入身份、设备/运行、遥测、共享限流、偏好/会话通知、控制连接绑定、原始批次、导出任务、设备控制范围和管理员申请/初始名单。迁移身份与运行身份分离，迁移校验和不可任意改写。

| schema | 数据用途 |
|---|---|
| `auth` | 账户、密码摘要、邮件验证/MFA、会话、注册审批、一次性初始管理员预留 |
| `security` | 限流与审计事件 |
| `ops` | 设备、控制租约、命令/运行事件与私有导出任务 |
| `telemetry` | 真实机械臂采样、批次/序号、来源和质量标记 |
| `simulation` | 个人模型点位；与真实遥测明确区分 |

真实遥测上传经设备身份、批次和序号校验，原始批次与结构化采样关联，缺失字段有可用性标记；历史记录不是当前实时安全状态。已有685条真实六轴采样验收和CSV下载证据，但此前端到端延迟不满足实时控制要求。日期与时间输入分别显示，支持日历选择/手工输入；查询、显示和CSV使用同一过滤条件。

成员CSV限管理员；观察员可查看/下载允许的完整机械臂运行记录。后台大导出使用独立worker和私有目录，下载再检查当前会话；超行数/字节/时间明确失败，不把截断文件当成功。

媒体接口`/api/v1/media/status`、`view`、`frame`、`close`分别提供状态、观看授权、解码反馈和关闭。LiveKit浏览器库及frame-metadata worker由**锁定npm依赖**通过鉴权资源路由提供，不需要在网页目录手工复制。观看重试有界，媒体授权异常不能自动降级成匿名视频。最新真实视频稳定性和采集UTC证明仍未通过，既往短时成功不能覆盖当前失败。

## 新拉取仓库所需资源

1. 安装Git LFS，正常clone后执行`git lfs pull`。URDF为普通Git文本，9件STL及本地SDK/大模型沿用`.gitattributes`的LFS规则。不得把LFS指针误当模型文件。
2. `assets/robot/startouch-v3`包含URDF和9件STL；`apps/web/public/js/lib`包含Three.js等本地网页库及二维码库/许可证。新cloud前端、identity/storage/edge源码、迁移、锁文件和部署模板均须纳入跟踪。
3. 根目录`npm ci`恢复Node workspaces与锁定依赖。`node_modules`不进Git。展示站独立执行自己的`npm ci --ignore-scripts`和build；它的字体、图片和视频在`showcase/public`，不依赖聊天附件或某台电脑的路径。
4. SDK/语音/视觉全功能本地运行仍按`local/README.md`及`tools/assets/setup_clone.sh`准备Linux平台运行时和LFS载荷；单独浏览模型不需要连接真实SDK。相机/PCAN驱动与设备权限属于主机配置。
5. 账户/点位/运行数据位于数据库；密码、私钥、真实管理员名单、设备证书、私有env、导出文件、outbox及日志不是Git资源。新服务器须生成独立密钥、初始化私有数据库并配置SMTP，不从仓库恢复真实账户数据库。

本次审核未发现缺失工作台资源：9件STL和URDF已跟踪，展示媒体注册表47项引用均有文件。展示站原ZIP未包含可选素材生成脚本或原始照片处理管线，已取消不可用的`npm run media`宣传；正常安装/构建使用已提供成品，不需要重新生成。

## 本地与云端运行

本地展示站（不会连接SDK）：

```sh
cd showcase
npm ci --ignore-scripts
npm run dev -- --host 127.0.0.1
# 或 npm run build，再 npm run preview -- --host 127.0.0.1
```

业务工作台使用Node24、PostgreSQL17、独立测试数据库、HTTPS反向代理和SMTP。不要在HTTP预览中关闭Secure Cookie来模拟生产。配置名见`services/cloud-api/.env.example`；模板只含占位符，真实值保存在检出目录外的受保护文件。Node不会隐式加载env：

```sh
npm ci
node --env-file=/etc/thirdhand/cloud.env platform/storage/src/migrate-cli.js
node --env-file=/etc/thirdhand/cloud.env services/cloud-api/src/main.js
node --env-file=/etc/thirdhand/cloud.env services/cloud-api/src/jobs/export-main.js
```

上面为新隔离环境入口，不是要求重置现有staging。当前staging使用专门`staging-main.js`、Unix数据库socket和独立systemd单元，私有文件在`/etc/thirdhand-stage`；部署模板在`deploy/public-access/staging`。PUBLIC_ORIGIN必须匹配HTTPS实际源，API仅监听loopback，Nginx覆写可信代理头。SMTP仅用465/TLS或587/STARTTLS，MFA与CSRF密钥分开。媒体及设备功能需要完整显式配置，否则保持关闭。

新云端按[C1/C2部署索引](../../deploy/public-access/README.md)准备DNS/TLS、私有数据库和角色、备份/WAL、API/export/media/relay单元；Ubuntu按`services/edge-agent/README.md`准备受保护证书/配置后主动连接。仅安装源码或模板不产生设备身份、证书、账户或硬件准入。对已运行站点应先核对current/清单和保护配置，再应用固定差异，不能把历史一次性应用器直接当任意新服务器安装器。

## 验证和未完成项

- 相关public-access/Robot Node348/348、C6部署Python5/5通过；覆盖真实隔离PostgreSQL、不同会话持久化、账户隔离、CSRF/数值/并发配额、模型插值/停止和请求超时。
- C6线上完整4634文件校验、私有最小权限、匿名接口401、真实点位入库/刷新/跨登录调用通过。无SDK/Ubuntu/机械臂动作。
- 更广的旧网页测试791项中771通过/20失败，涉及已记录的Windows权限和旧夹取/标定夹具；未宣称全仓绿。CI在Linux运行，结果仍需查看实际远端任务。
- 新手教程正式内容由队友完成，合并时接既有adapter；本地账户化进度不是最终教程。
- 真机实测点位、独立物理停止、机械限位/新基线、夹爪标定、当前相机稳定视频和采集UTC、实时遥测容量、真实密码重置及生产正式发布仍待完成。
- 用户在一次Observer重新登录期间报告长时间转圈，随后登录成功。当前健康检查通过，但未取得该认证POST耗时和浏览器加载时间证据，原因未定位，不能称作已修复。

Git交付偏好记在根目录`AGENTS.md`：独立功能完成且必要检查通过后自动本地提交，同步说明，报告提交号；本次普通推送fork的login分支，保留历史和其他任务改动。

后续[CI修复记录](../operations/2026-11-01-ci-repair.md)说明数据库清理、关闭握手前撤权、只读来源摘要、LF/LFS资源和UI测试夹具的修复；完整公网/Robot回归现为350/350。这些仓库修复未额外部署到现有服务器，不推导出真实物理停止或运动已验收。

## 后续界面与只读状态整理（C8，设计待审批）

[C8审计与设计方案](../operations/2026-11-01-C8-ui-sdk-audit-and-design.md)记录真实页面、合成角色浏览器与代码链路证据，
提出导航/账户分层、保留两布局、复用教程和独立最新状态同步的统一实施方案。
本轮仅审计和文档，未部署新状态接口、修改业务代码或连接SDK；真实最新历史样本已过期，不能作为当前连接证明。
现有测试通过不代表没有视觉问题：浏览器断言复现了经典管理员顶栏裁切、确认框偏位和观察员教程末步卡住，详细结果及未测项目见方案。

## 双布局与加载优化（C7，已部署staging，真实会话界面验收通过）

账户偏好新增`layoutId=workspace|classic`及独立的`classicThemeId`，默认新版、英文。
经典版直接复用主仓库`372ac80a98e279e85bd25dfe8f219b399b97cb80`的原始HTML/CSS，
保留全屏模型、顶部连接工具和原右侧浮动抽屉，不重设计为新版导航结构。
原始文件逐字节校验来源记录在`configs/web/classic-source.json`；新增账户/相机/运行记录入口及个人点位使用现有鉴权业务适配器。
原版`main.js`的SDK/WebSocket/语音启动流程不会被云端加载。

`/control`由当前会话读取数据库外观和显示名，在HTML首屏确定模板、语言和配色。
账户摘要、退出、相机入口及会话监测先初始化，Three.js和模型随后独立加载；请求超时可重试，网络超时本身不注销有效会话。
切换布局先保存、再重新请求对应模板；快速连续改变主题/语言按数据库revision顺序保存。
`011-workspace-layout.sql`为兼容旧代码的加列迁移，不新增角色或设备权限。

网页模型为完整STL生成的`web/robot-visuals.glb`，gzip为1,918,246字节，原STL/URDF继续保留。
保留448,604个三角面的顺序、绕序和float32顶点位置；法线由几何面重建，未保留原STL法线属性的逐位表示。
GLTFLoader匹配现有Three.js r163，Meshoptimizer固定0.22.0，均附许可证；只为解码增加CSP `wasm-unsafe-eval`。
使用Git LFS恢复`assets/robot/startouch-v3/web/*.glb*`；重建及校验说明见该目录README。

鉴权静态资源使用内容版本URL、ETag及`private, max-age=31536000, immutable`，减少刷新/再次登录重复下载。
HTML、身份和动态API保持`no-store`，每次网络请求仍验证会话，缓存只含源码/可视化资源，不含身份、MFA或控制权限。
相机客户端库仅在点击观看时加载；模型失败不阻塞相机入口。

详细模块、数据流、测量和限制见[C7实现记录](../operations/2026-11-01-C7-workspace-layout-startup.md)，
固定32文件、迁移、重启和回退范围见[C7部署审阅](../operations/2026-11-01-C7-deployment-review.md)。
C7已获具体批准并部署到staging；完整发布、迁移、保护配置及匿名HTTP鉴权已复核。
真实HTTPS会话已验证双布局往返、经典抽屉开合、模型加载与既存点位调用、刷新保留布局/英文/配色，以及观察员SDK连接禁用。
本轮未退出再登录，真实跨登录偏好和公网缓存传输量未单独实测；相机入口可打开，但加载相机后目录为空、显示不可用，视频不记为通过。
不推导校园网已提速或真机运动已通过。验收后恢复原新版/中文及经典默认配色，保留观察员模式。

## C8：统一入口与独立只读状态（本地候选，尚未部署）

用户已批准 C8 设计；实现记录和验收边界见
[C8 实施记录](../operations/2026-11-01-C8-implementation.md)。
账户拆为资料、安全与登录、偏好、管理员成员与权限；历史、导出、回放归入数据。
经典界面继续复用原始 HTML/CSS 和全屏模型、右侧抽屉；两布局共享操作含义。
旧 `account-connections` hash 保留，新版转到设备页。既有点位和教程进度不迁移、不清空。

`GET /api/v1/devices/:id/state` 为鉴权、no-store 的当前快照；原 telemetry 接口仍是历史查询。
Ubuntu 新增独立 state 进程，从已有只读 Robot 事件流取最新一条，经 mTLS、设备签名
POST `/edge/v1/state`；不等待历史积压，不自动连接 SDK。源/云/浏览器三端约束年龄、代际和序号。
六轴 rad 转度、夹爪比例转百分比、宽度米转毫米；未知字段不填零，法兰与工具 TCP 分开。
页面一个 store 统一更新状态灯、六轴、夹爪和设备详情；模型姿态不受其覆盖。

无需数据库迁移、新依赖或新公网端口。Nginx 模板为
`deploy/public-access/staging/device/state-location.conf`；只加入现有严格 mTLS server。
仍使用现有 Node24、PostgreSQL17、Python 代理虚拟环境和原启动入口。
代理配置不新增字段；状态进程由现有 `python -m thirdhand_edge.runtime --config ...` 管理。
模型资源、原 URDF/STL、经典原版文件及依赖未改变，克隆恢复方法沿用 C7。

实时缓存绑定现有单实例设备中继，不支持多个独立进程各维护一份状态；扩容前需共享缓存和路由设计。
快照不持久化；已有采集进程仍把样本、连接/断线/读取错误事件写入历史库。
快照 HTTP 故障表现为过期/读取失败，不能冒充 SDK 故障或已确认物理停止。
本轮运动保持禁用，不提供模型跟随；真实 SDK 连续 10 分钟验收需具体部署获批后进行。

## C8 现场部署补记（2026-11-01）

**SDK权限方案（现已部署，验收未完成）**：用户已允许观察员显式连接普通 SDK（含初始化使能与夹爪闭合），后续运动仍需管理员。实现通过 sdk/control 两种签名租约、数据库会话复核和设备侧白名单隔离权限，新增迁移012；已部署。模块、权限矩阵、测试及启动/回退边界见 [SDK连接权限](../operations/2026-11-01-sdk-connection-permissions.md)。此前“观察员 SDK 禁用”和被动初始化阻塞描述为历史部署状态，不再是最新目标策略。

SDK续查补齐真实 Python 网关与云端中继的 scope 校验/ACK 白名单，避免模拟链路通过而现场授权失败。340项 public_access、88项 Python网关、20项部署边界测试通过。云端11文件和设备8文件的组合候选包含实际路径修正与独立最新状态上传；两端默认只读预检通过，现已按批准范围激活。固定包、迁移012、服务启动和回退流程见 [SDK部署审阅](../operations/2026-11-01-sdk-scope-deployment-review.md)。本地及CI使用测试设备，真实SDK十分钟验收尚未完成。

登录新增灰色禁用按钮、转圈、请求/偏好/导航分阶段提示和超时恢复，中英文可用；成功认证后重试导航不重复提交密码。三件前端文件、无数据库或配置变化，本地浏览器及认证12项测试通过，已按用户批准上线 release `dfbca02d47ca7f40`。公网资源摘要、服务健康和双语页面通过核验；未再次提交用户凭据。见 [登录等待反馈](../operations/2026-11-01-login-wait-feedback.md)。

SDK只读接入后续核验发现现场原生库普通初始化包含电机使能和条件夹爪闭合调用，不满足无动作只读验收；官方被动读取示例依赖缺失的 startouchlib/print_joints。来源、固定库摘要、静态证据和需要补齐的实现见 [SDK初始化核验](../operations/2026-11-01-C8-sdk-initialization-audit.md)。未执行初始化或改变运行配置，修正版部署暂未应用。

云端导航/账户分组及最新状态路由已上线；设备端原候选因目标目录未被服务加载而回退并停用。具体运行路径、验收证据、回退和未完成事项见 [C8部署记录](../operations/2026-11-01-C8-deployment-change.md)。本次没有数据库或权限变更，SDK仍未连接，真实10分钟采集与相机观看均未通过本轮验收。

本地后续修复让 SDK 连接按钮在请求完成或失败后结束“正在连接”，刷新只读状态；15秒后也不能永久显示等待。请求结果不推断物理连接或停止状态，仍以独立实测反馈为准；同时补充未知状态中文。模块为 `device-state.js`、`admin-control.js`、`i18n-cloud-catalog.js`，无新依赖/资源/配置，沿用现有本地预览和 staging 启动方式。相关 Node13项、设备退役/回退 Python6项通过；此后续补丁尚未上线。

## SDK接入最新状态（2026-11-01 18:40后）

已批准的云端11文件/迁移012及Ubuntu8文件/两个服务入口配置已应用；当前云端发布 dc458eb35ed369a1 另包含单文件非阻塞连接确认修复。初始化仍需用户显式确认，后续运动保留 readOnly 门禁。观察员 sdk 范围租约真实下发和续期有设备日志证据，但最近因 browser_stale 撤销；SDK未初始化，连续10分钟真实数据与本轮视频验收均未通过。历史段落中的“尚未部署”仅描述当时阶段，以 [SDK实际记录](../operations/2026-11-01-sdk-scope-change.md) 为准。

用户登录无转圈的现场问题仍待复现；公网等待组件存在且16项相关前端测试通过，不据此声称用户问题已解决。无额外配置或依赖变化，启动与回退沿用固定部署审阅。其他任务的相机源码改动保持未提交、未混入本次发布。

SDK心跳前端后续修正：有效确认允许对应较早已发送的挑战，但单调性、真实性和500ms年龄限制保留；迟到的租约HTTP结果不能恢复失效通道。授权失效在设备页明确显示。16项相关测试通过；本轮登录转圈在Edge未再复现。该修正已按追加批准发布为3d3acd1d9fa353a0，CI #47通过；真实验收续期65次后在设备端到期。没有新connect命令，10分钟实测尚未通过，见SDK实际记录。

2026-11-01 Wi-Fi临时对照已获批并完成：原15分钟自动恢复定时器先行建立，关闭节电后仍出现mTLS长连接1.063秒响应；已恢复原节电on，SDK断开且无运动。最初HTTP400样本实际每次重新握手，已明确修正测量口径，不能当作稳态续期延迟。补测每阶段40次、单TCP连接的on/off/on结果均保留；未判定节电为根因、未执行SDK初始化或10分钟真实状态验收。见[Wi-Fi对照记录](../operations/2026-11-01-sdk-wifi-ab-review.md)。

21:30后双端TCP元数据核验：Observer租约确认后约2秒失效，renewal_failed；同一设备通道下行报文发生两次重传，累计588.682ms，Ubuntu只收到第三次发送。最后一次续期设备仍返回active，内部失败异常尚需细分，不能误记为renewal_unconfirmed。未新增connect，SDK真实十分钟验收未通过。云端未安装Tailscale，当前业务走公网443；本轮无配置变更，节电已恢复并确认定时恢复成功。见[双端诊断证据与下一步](../operations/2026-11-01-sdk-tcp-diagnostic.md)。

后续续期修复已部署为671809219c9cefc8：保留设备ACK等待期间最新的一次浏览器新鲜事件，ACK返回后串行复核并立即续期；新增异步边界撤销检查和白名单失败诊断。500ms/1000ms期限、权限及只读门禁不变。352项本地回归及候选CI通过；真实授权复测仍出现renewal_unconfirmed和grant_failed，没有新SDK初始化，十分钟状态验收未通过。只改云端两份源码，无数据库/Ubuntu/端口/依赖变化。后续单文件白名单确认拒绝诊断已完成本地21项组合验证，尚未部署；见[续期修复记录](../operations/2026-11-01-sdk-renewal-queue-fix.md)。

2026-11-02最新：诊断候选1cae07dc97cc0d04之后，有界发送候选cdf9c84已获批并部署为805921eeb03285b8。发送与ACK等待分离，串行复核/发送、最多4个在途确认及1个待处理心跳，原500ms/1000ms和运动门禁不变；仅更新云端两份源码，无其他配置变化。364项本地回归、21项包边界及CI通过。两次真实授权仍到期，第二次在新Observer会话中确认后保持22.728秒、云端续期序号88，最终renewal_unconfirmed；不能记作稳定性通过，也不能将失败诊断总耗时直接当作纯网络延迟。SDK未初始化、真实十分钟状态验收仍未完成。实现、启动、回退及下一步时序核对见[SDK续期发送修复](../operations/2026-11-02-sdk-renewal-pipeline.md)和其部署实际记录。

后续分段诊断已按批准固定包部署为f72e61d85009b7ea，实际授权诊断后两端开关已关闭（见[现场结果](../operations/2026-11-02-sdk-segment-timing-change.md)）：cloud leases记录排队／身份／准备／DB／签发／ACK，中继记录注册／写入／ACK，Ubuntu记录验签／锁等待／本地HTTP／回复；以现有签名载荷匿名摘要关联，不改协议。新lease-timing.js、lease_timing.py默认关闭，THIRDHAND_SDK_TIMING=1启用后每个记录器最多600秒／12000条，测试后撤销临时开关。无依赖、数据库或权限变化，沿用现有服务启动方式；Ubuntu新模块必须随bound_transport.py一起发布，不能只复制入口文件。离线工具tools/operations/summarize_sdk_timing.py只汇总白名单数据，跨主机墙钟差不是单向网络延迟证明。完整本地公网访问366/366及Python网关92/92通过；首次受限Python完整运行无输出后中止，允许本机网络的重跑通过，不能算首次通过。SDK生命周期／多人状态订阅／管理员独占运动权的分离仅为设计，尚未改变线上行为；允许考虑的2s／3s读取保持有效期也未应用，500ms／1000ms限制保持。具体模块、API、数据库、迁移、回退、验证与边界见[分段诊断与分离方案](../operations/2026-11-02-sdk-separation-design.md)。

现场取得3条完整cloud／relay／edge续期记录，往返40–111ms，其中2条在代理验签后、调用本地HTTP前被拒绝；离线24项断言复现设备时间略早于签发时刻导致剩余时长大于1000ms而被误拒。下一步优先统一代理、Robot Node及Python guard的签名跨度与单调截止语义，保留本地1000ms上限；尚未实施或上线该逻辑修复。SDK未初始化，真实10分钟状态验收仍未完成。数据库、权限及网络不变，运行配置恢复THIRDHAND_SDK_TIMING=0。

## 2026-11-02 注册密码规则（已上线）

用户指定新密码至少8位，同时包含大写和小写英文字母。注册和重置共用8–128个Unicode字符、最多512字节的规则；必须含A–Z和a–z，数字和符号可选。`platform/identity/src/passwords.js`在服务端强制校验；`auth-page.js`同步两密码框实时反馈及底部要求，`i18n-auth-catalog.js`和重置页同步中英文文案。`accounts.js`的未知账号占位哈希使用保证满足大小写的随机输入，避免新规则影响登录初始化。

已有密码哈希与验证流程保留，旧账号不会因新规则被拒绝登录；重置新密码必须满足新规则。无数据库迁移、依赖、账户角色或SDK变动，沿用现有本地与cloud启动命令。23项认证测试通过，包含真实隔离PostgreSQL注册/验证/重置/登录、8字符边界、大小写缺失、Unicode上限、旧密码兼容及双语实时提示。第一次受限环境页面HTTP测试因127.0.0.1 EACCES失败；允许本机连接后全部通过。测试数据库已停止。用户批准后已上线为e3f0176566d900ed，仅替换5件、保留4653件，只重启业务API。线上资源摘要与双语提示核验通过，旧密码登录兼容；未创建真实测试账号或发邮件。部署与回退见[固定审阅及实际记录](../operations/2026-11-02-password-policy-deployment-review.md)。

## 2026-11-02 SDK时钟修复（已上线，稳定性未通过）

代理、Robot Node和Python guard统一以签名跨度≤1000ms检查租约长度，允许既有小幅未来签发容差，同时保留本地单调截止最多1秒、过期不可恢复。修复跨主机墙钟差导致有效租约被误拒，不延长续期或任何超时。网页申请增加等待、禁用和防重复提交、明确失败原因，以及授权成功后仍需显式连接SDK的提示，中英文同步。5件运行源码，无数据库/权限/依赖变化；使用既有服务，派生实际运行快照部署。141项Python通过，392项Node覆盖项经完整运行及解释器修正后的定向补测完成验证；无真实SDK初始化，连续10分钟真机状态尚未验收。已知问题、模块、数据流、启动、验证口径见[时钟与申请反馈修复](../operations/2026-11-02-sdk-clock-fix.md)。

用户批准后云端已切换d5284b8679ff90e8，Ubuntu两个快照及入口配置已应用；首次授权续期3次后以browser_stale释放，没有初始化SDK或发送运动。后续发现第四层Node→Python桥接重复时钟检查，纳入下一包。

## 2026-11-02 SDK浏览器心跳（本地修复，待固定候选部署）

按用户允许放宽超时，观察模式SDK浏览器窗口改为3秒、最多12条待处理回复；管理员运动模式仍500ms/2条。原挑战年龄决定有效期，迟到回复不能刷新整个窗口。SDK在有效浏览器证明内每至少250ms续约，仍逐次校验身份、设备与数据库；每条设备签名/本地租约仍1秒，ACK1500ms及4条在途不变。页面隐藏/退出/权限撤销/过期后停止续约且不自动恢复，不初始化SDK。补齐startouch-bridge时钟跨度校验，并记录不含凭据的浏览器拒绝阶段耗时。

云端5件源码、Ubuntu1件，无数据库迁移/依赖/新端口。400项公网业务回归及9项固定包测试通过，源码边界ready，40d2dac的两个CI job成功；真实10分钟授权稳定性尚未验证。Ubuntu初始SSH/Tailscale探测超时，后TSMP和SSH恢复，现场基线与SDK断开已核验；未改网络配置。模块、时限边界、启动、测试及剩余工作见[修复记录](../operations/2026-11-02-sdk-browser-heartbeat-fix.md)，待[固定候选部署](../operations/2026-11-02-sdk-browser-heartbeat-deployment-review.md)。
