# C4 展示站控制入口和表格下载

2026-10-31，按用户提供的 `ThirdHand-website-source-20261031.zip` 检查和修改。范围为展示站跳转及控制站数据下载，不连接 SDK、不操作机械臂。

## 源码核对

原压缩包 SHA-256：`00513d2a0939104a182fd680d65516753dc3d552eb22e166d089cd1d2a38b3cd`。

这是独立 React/TypeScript/Vite 展示站。按其锁文件构建后，与当前 `https://uiea-thirdhand.com/` 的两个资源**逐字节相同**：

| 文件 | SHA-256 |
|---|---|
| 原线上 index.html | `639bb62379c763ebbd4610125cafc3ebff3aa14debb0c3ca2f50ee75d1a478bd` |
| index-CL3W_Xbj.js | `f697f4cdaf068b1f310d1c9f98097d28a5c6e39bde8e161d70152d3d2ad8a3a9` |
| index-DwGmTHpk.css | `b7cafce118bd2d03ef0606902d7baaee702ce266bab604518441ceb92ef54fe3` |

源码存放于 [showcase](../../showcase/README.md)，使用自己的锁文件。独立于控制仓库的 npm workspaces；`node_modules`、构建物、原始 HEIC 素材和运行环境不加入 Git。

## 修改

- 展示站首屏增加 `Open Control` 主按钮，顶部原动作介绍按钮位置改为控制入口；原 Actions 导航与项目介绍入口保留。手机菜单也增加入口。统一跳到现有 `https://staging.uiea-thirdhand.com/login`，保留正常登录、默认 Observer 和 MFA。
- 管理员账户页增加 `Download members (CSV)` / `下载成员表（CSV）`。服务端独立授权检查，仅管理员模式可下载；导出全部成员而非已加载的一页。固定字段为 ID、用户名、显示名、邮箱、组织、角色、状态、语言、注册和邮箱验证 UTC 时间。密码、哈希、MFA、恢复码不在查询或导出字段中。超过 10,000 人明确拒绝，不截断。
- 运行历史默认 CSV，可在既有筛选条件下创建后台导出、检查进度、下载。六轴角度分列为 `j1_position_deg`–`j6_position_deg`，并包含各轴速度/电流/力矩/温度、TCP、时间和来源等可用字段；未知字段留空。命令和事件同样分列，`record_json` 保留完整运行记录，NDJSON 继续保留。
- CSV 使用 UTF-8 BOM、UTC 时间和明确单位；逗号、引号、换行正确转义，用户可控公式文本加防护。成员表仅管理员可下载；运行数据管理员和观察员仍按既有权限下载，文件仍为私有鉴权下载，不发布公开数据链接。

## 验证与发布

本地业务限定回归 **149/149** 通过，真实隔离 PostgreSQL 覆盖后台 CSV 完整导出；包含敏感字段排除、观察员拒绝、超过默认分页的全部成员、公式文本和缺失值。首次测试环境误用默认端口和系统 Python 已纠正；最终使用 55442 和项目独立 Python 环境，数据库已自动停止。没有改动机器人运行逻辑。

展示站 TypeScript 与 Vite 构建通过；桌面首屏正常，手机首屏按钮按行换行且不溢出，菜单可访问控制入口。新 JS 为 `assets/index-BZI2xPSt.js`，CSS 和媒体不变。

精确业务补丁只有 6 个文件：账户页 JS、双语词条、历史 HTML、导出 worker、管理员路由、新 CSV 生成模块。业务发布物 `4e858d8b13b8ea6b`，manifest SHA-256 `bd55cb3d54971c90f5d36d9c2114bc2c454693ed4f0680d8ea70ccfaa57fb8aa`；二进制补丁 SHA-256 `2416418fa763c02f4b27cfe4f974f9cf85f9fdb78867370695d295ac844a7505`。

发布目标为现有业务和导出服务，以及 `/www/wwwroot/uiea-thirdhand-static/index.html` 和新哈希 JS；无需 Nginx、数据库结构、凭据、端口或角色变更。实施前校验旧发布物全部文件、原展示页/JS/CSS 哈希、当前没有正在执行的导出，并备份 index 和原发布指针。切换业务和 worker 后健康检查，再原子替换展示页；旧 JS 保留供缓存中的旧页面使用。

备份及实际执行记录目录：`/var/backups/thirdhand/access-C4-showcase-tables-20261031`。工具 [apply_showcase_tables.py](../../tools/operations/apply_showcase_tables.py) 默认只审阅，`--apply` 才实施，发生异常恢复原展示 HTML、原业务发布及两个服务；不删除历史记录或重放命令。

实际发布已于 **2026-10-31 18:56:16 中国时间** 完成，业务与 worker 均切换到 `4e858d8b13b8ea6b`，健康检查通过，授权环境哈希保持一致。线上新 index SHA-256 为 `45d48a7b469fcb7b7319742c60b6d1db3ded4bc62a3c9a8dcdccbd6b502b0782`。

18:57:43–18:57:46 的真实 HTTPS 下载验收通过，使用已有合成管理员/观察员的正常登录流程；没有读取或代填用户自己的密码、验证器或恢复码：

| 实际检查 | 结果 |
|---|---|
| 管理员成员 CSV | HTTP 200，6 条现有账户、10 列，与数据库总数一致；UTF-8 BOM、附件下载、no-store |
| 观察员成员 CSV | HTTP 403 |
| 机械臂 CSV 后台导出 | 观察员按只读设备/采样时间筛选，完整 685 条真实记录、54 列，SHA-256 与任务及下载响应头一致 |
| 表格内容 | 六轴实测角度分列，hardware 来源，未运动，未提供的电流留空，无非法补零 |
| 未登录访问运行数据下载 | HTTP 401 |
| 其他账号访问该导出任务的文件 | HTTP 404；管理员同样不能借任务 ID 读取别人的私有导出 |
| 浏览器展示入口 | 线上首屏及导航均有入口；实际点击跳到英文 `/login`，Observer 默认选中 |
| 发布前设备状态 | SDK 断开，只读采集健康，源序号 703；本轮 SDK/运动操作均为 0 |

验收结果保存在服务器 `table-download-acceptance.json`，脚本为 [staging_table_download_acceptance.cjs](../../tools/diagnostics/staging_table_download_acceptance.cjs)。下载内容仅在测试进程内校验，没有把成员隐私或机械臂 CSV 发布到公开路径。已有验证导出任务按原有 24 小时有效期管理。用户自己的下载仍需自己的有效登录会话。

使用位置：管理员在 Account and settings → Profile → Registered users 点击 `Download members (CSV)`；任一已注册角色在 Run history 选择时间、设备和记录类型，再在 Private export 选择 CSV → Create export → Check export → Download export。

此前 C3a 相机授权超时、续租稳定性和实时入库延迟不属于本次已解决项，完整运动权限继续关闭。没有 Git commit/push/PR。
