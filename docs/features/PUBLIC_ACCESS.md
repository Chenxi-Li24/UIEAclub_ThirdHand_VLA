# 公网工作台：实现、资源和运行说明

本说明对应2026-11-01的login分支实现。展示站为`uiea-thirdhand.com`；登录/控制业务目前在`staging.uiea-thirdhand.com`，最新实际发布为C6。实际状态以[集成状态](../integration/public-access-implementation-status.md)和[部署记录](../operations/2026-11-01-C6-model-waypoints-change.md)为准。代码具备的接口不等于真机运动已获准。

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
