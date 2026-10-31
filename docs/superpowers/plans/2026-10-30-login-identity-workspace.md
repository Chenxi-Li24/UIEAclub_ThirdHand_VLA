# ThirdHand Identity and Workspace Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement task-by-task after the user reviews the execution plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 完成注册、人员登录、两角色、模式、偏好和只操作 Three.js 的观察员工作台。

**Architecture:** 新增独立人员身份模块及私有 PostgreSQL 业务层，复用现有静态页面和 i18n。云端代码不实例化 RobotProxy 或任何设备 SDK；通过只读和后续设备中继接口接收数据。

**Tech Stack:** Node.js 24、pg、Argon2id、成熟 TOTP 实现、现有 node:test、Three.js、浏览器会话 Cookie。具体补丁依赖实施时按官方文档核验后锁入 lockfile。

**Spec:** [设计 v0.4.1](../specs/2026-10-29-public-access-roles-database-design.md)；[总计划与全局约束](2026-10-30-public-access-rollout.md)。

## Global Constraints

继承总计划全部约束。首期同域，首次默认 en/light/Observer；不创建可自行授予管理员的注册参数；管理员模式 MFA，模式改变不自动抢占设备。教程只接队友接口，旧动作授权模块不是人员登录模块。

## Review Focus

伪造角色与 mode、跨账号偏好污染、管理员观察模式越权、教程不可用与返回循环、观察员触发旧裸命令通道，分别由 A2～A5 归属测试覆盖。

## A0 基线与协作契约

**Files:** 创建 `docs/integration/showcase-source-map.md`、`docs/integration/tutorial-adapter-contract.md`；核对 `package.json`、`.github/workflows/ci.yml`，本任务不改其产品行为。

**Interfaces:** 输出展示站的源仓库/提交、首页与导航实际源文件映射、构建/回退位置。`TutorialAdapter.getState({userId}) -> Promise<{status,version?}>`，status 仅 unavailable/not_started/in_progress/deferred/completed；`getEntry({locale,theme,returnTo}) -> {path}|null`，只允许站内获准路径；`verifyCompletion({userId,version}) -> Promise<{trusted,completed,version}>`。真实队友接口在合并时绑定，不指定其内部数据库；未接入时 unavailable/null，不能产生可信完成。

- [ ] 在 login 检查工作区、重新 fetch origin main，比较基线；保留未提交设计文档，若基线变化先展示差异，再选择合并方式，不 hard reset 或强行覆盖。
- [ ] 只读检查展示站实际源文件与发布目录，写入 source-map；只有构建产物时向对应源码/队友取得来源，不热改线上压缩 JS。没有源码不会阻止后端开发，但阻止展示入口上线验收。
- [ ] 与队友按契约记录入口、用户标识、状态、版本、语言主题与返回方式；未合并时适配器固定返回 unavailable，不伪造 completed。
- [ ] 依照当前锁文件运行原有无硬件检查并记录基线失败；本工作树二进制初始可能是 LFS 指针，只恢复测试需要的资产。不得启动 manual-control 或连接 SDK 作为测试。

## A1 PostgreSQL 结构与仓储

**Files:** 创建 `platform/storage/package.json`、`src/pool.js`、`src/migrate.js`、`src/users.js`、`src/sessions.js`、`migrations/001-identity.sql`、`002-devices-runs.sql`、`003-telemetry.sql`；创建 `tests/node/public_access/storage.test.js`；修改根 `package.json`、lockfile 和 CI，增加可单独运行的身份/存储测试，不移除现有测试。

**Interfaces:** `createPool({connectionString,max}) -> Pool`；`migrate(pool) -> Promise<void>`；`users.create(input)`、`users.findByLogin(login)`、`users.setRole({actorId,userId,role,expectedVersion})`；会话仓储由 A2/A3 使用。完整列名按设计第 9 节，JSONB 不替代关键约束。

- [ ] 写迁移测试：空库可建立；重复迁移不重复执行；同账号/邮箱唯一；角色仅 observer/admin；默认 locale=en；每账号允许多个会话；最后一个 active 管理员不能被并发降级。
- [ ] 运行 `node --test tests/node/public_access/storage.test.js`，确认缺失实现导致失败；使用专用 TEST_DATABASE_URL，缺少时明确报告未测试，不假装通过。
- [ ] 实现事务、迁移版本/锁、参数化 SQL、最小连接池；建立设计中的外键、时间分区和批次约束。用户停用不级联删除历史；队友教程表不在本模块重复创建。
- [ ] 重跑上述测试；在隔离库验证迁移和回退/前滚恢复，不使用生产数据库做删表试验。后续 B4 对采样约束再做并发验证。

## A2 注册、邮件、密码与 MFA

**Files:** 创建 `platform/identity/package.json`、`src/accounts.js`、`passwords.js`、`mfa.js`、`tokens.js`、`mail.js`、`bootstrap-admin.js`；创建 `services/cloud-api/src/server.js`、`routes/auth.js`；创建 `tests/node/public_access/accounts.test.js`、`mfa.test.js`。

**Interfaces:** `register({username,email,displayName,password,locale}) -> {userId,status}`；`verifyEmail({token})`；`authenticate({login,password,requestedMode,totp}) -> SessionResult`；`bootstrapAdmin({verifiedUserId})`；邮件 `send({purpose,to,url})` 可注入测试适配器。调用 A1 用户仓储，密码仅保存 Argon2id 哈希，验证码和恢复码仅保存摘要。

- [ ] 写测试：注册总是 observer；传入 role=admin 不提升；验证令牌一次性；重置密码不泄露账号存在性；无管理员权限不能登录 Administrator；密码错误时不先透露角色。
- [ ] 写 MFA 测试：未完成 MFA 无管理会话；恢复码只能用一次；重置密码不能绕过 MFA；首次管理员必须先正常注册/验证，再由受控 CLI 提升，先注册者不自动变管理员。
- [ ] 运行 `node --test tests/node/public_access/accounts.test.js tests/node/public_access/mfa.test.js` 确认红灯后实现对应接口。TOTP 密钥独立加密，配置登录/邮件限速；测试邮件只进入假邮箱，不向真人发送测试通知。
- [ ] 同一命令验证绿灯；检查响应、日志、导出不含明文密码、令牌或 MFA 密钥。SMTP 与引导提升的生产操作另做具体审阅。

## A3 会话、模式与管理 API

**Files:** 创建 `platform/identity/src/sessions.js`、`policy.js`、`csrf.js`；创建 `services/cloud-api/src/routes/admin.js`、`session.js`、`workspace.js`；创建 `tests/node/public_access/sessions.test.js`、`policy.test.js`、`admin.test.js`。

**Interfaces:** `resolveSession(request) -> Promise<Principal|null>`；`authorize(principal,action) -> {ok,code}`；`setMode({sessionId,requestedMode,mfaProof})`；`revokeSession({sessionId,reason})` 发出统一撤销事件。`Principal={userId,sessionId,role,mode,roleVersion,mfaVerifiedAt}`，后续通道复用它，不信任前端 userId。

- [ ] 参数化测试覆盖每个设计权限：observer 可以 telemetry/history/export/simulation/video；不能 sdk/voice/control/admin；admin 在 observe 模式同样不能越权；未登录默认拒绝。
- [ ] 测试 Cookie 为 Secure/HttpOnly/SameSite=Lax，CSRF 失败拒绝变更；观察模式 60 min 闲置/24 h 最长、管理模式 15 min/8 h；心跳不刷新用户活动；同账号多个会话可并存，单端退出不误踢其他端。
- [ ] 运行 `node --test tests/node/public_access/sessions.test.js tests/node/public_access/policy.test.js tests/node/public_access/admin.test.js` 得到预期红灯后实现服务端权限、版本撤销和管理路由；退出/降级事件供 B1/B3/B6 关闭长连接、撤销控制与视频。
- [ ] 重跑绿灯；HTTP 与 WebSocket 入口共享政策，不把 `authorized:true`、请求头或 URL 当作人员身份。此时真实硬件路由仍固定 unavailable。

## A4 独立登录页、主题与语言

**Files:** 新增 `apps/web/public/login.html`、`register.html`、`forgot-password.html`、`css/auth.css`、`js/auth-page.js`、`js/preferences.js`；更新现有 `js/i18n-catalog.js`、`i18n.js`；新增 `services/cloud-api/src/routes/preferences.js` 与 `tests/node/public_access/auth-ui.test.js`、`preferences.test.js`。

**Interfaces:** `preferences.load({principal,guestSelection}) -> {locale,themeId,backgroundConfig,revision}`；`save({principal,value,expectedRevision})`；UI 调 A2/A3，不保存认证令牌到 localStorage，不改变硬件命令载荷。

- [ ] 用绘图工具先提供新的浅色英文登录、注册、Observer/Administrator 标签与无权限错误状态效果图；按用户四张参考绘制，取得视觉审批后再编写本任务 UI。
- [ ] 写 UI/偏好测试：无偏好 en/light/Observer；每次新登录仍默认 Observer；已有主题和语言可恢复；共享电脑不把上一账号缓存写入下一账号；存储禁用仍能登录；输入错误、无管理权限和 MFA 状态有中英文提示。
- [ ] 运行 `node --test tests/node/public_access/auth-ui.test.js tests/node/public_access/preferences.test.js tests/node/web/i18n.test.js` 确认红灯后实现清晰可降级的玻璃卡片、键盘焦点、主题同步与服务端修订检查；不复制 CodePen 示例认证或第三方品牌。
- [ ] 同一命令绿灯后浏览器实测桌面/窄屏、密码显示、键盘和高对比度/减少动画。效果图审批不等于账号后端已经通过安全测试，分别记录。

## A5 模拟隔离、教程适配与展示入口

**Files:** 新增 `apps/web/public/js/simulation-controller.js`、`js/tutorial-adapter.js`、`js/workspace-session.js`；修改 `js/main.js`、`index.html`；新增 `services/cloud-api/src/routes/tutorial.js`、`simulation.js`；测试 `simulation-isolation.test.js`、`tutorial-adapter.test.js`、`showcase-entry.test.js` 放在 `tests/node/public_access/`。展示站修改路径必须来自 A0 source-map，不把生产静态目录误当已入库源码。

**Interfaces:** `createSimulationController({armModel}) -> {setJoints,playPreset,playSequence,stop}`，不接收 SDK/控制 socket；`TutorialAdapter` 遵循 A0；`resolveEntry({principal,tutorialState,returnTo}) -> localPath`；`dispatchRealCommand` 仅在 B3 通过后接入。

- [ ] 写测试：observer 滑条/固定点/动作序列/历史回放的真实 commandSink 调用次数为 0；两个观察员模拟互不覆盖；实时镜像不覆盖正在编辑的模拟；访问旧 `/ws`、`/execution`、`/voice` 不获得代理连接。
- [ ] 写教程与入口测试：新用户先进教程；适配器 unavailable 不伪造完成；deferred 不循环跳转；主题/语言正确传入；return_to 外站拒绝；首屏和导航两个按钮都进入相同路由，不自动 connect。
- [ ] 运行 `node --test tests/node/public_access/simulation-isolation.test.js tests/node/public_access/tutorial-adapter.test.js tests/node/public_access/showcase-entry.test.js` 得到预期红灯后完成隔离与适配。队友接口未合并时保留明确状态，不能做假完成教程。
- [ ] 重跑绿灯并演示 A 阶段：两角色登录、观察员模型操作、用户后台和模拟数据；硬件路由仍 unavailable，确认无 Startouch 导入和 SDK 连接副作用。

## A 阶段交付

- [ ] 根 package 脚本与 CI 收集本目录新增测试，接入隔离 PostgreSQL 服务；不能只写未被 CI 执行的测试文件。
- [ ] 对照设计权限矩阵演示、复核文件范围、生成该阶段提交说明；提交和推送按用户授权执行。
- [ ] 将真实教程接口和展示源映射在代码合并时绑定；未绑定时不得将相应入口标成生产验收通过。
