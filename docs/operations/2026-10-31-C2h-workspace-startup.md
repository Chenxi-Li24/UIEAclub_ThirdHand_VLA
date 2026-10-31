# C2h 登录后工作台加载修复（2026-10-31）

状态：修复已部署，完整业务回归 133/133 通过、0 跳过；用户已确认 Observer 登录成功。真实浏览器已观察到账户、退出与相机操作在模型仍显示 Loading model 时可用。C2g 视频故障和长期稳定性单独记录。

## 问题与证据

用户反馈“最开始一直转圈，再试提示次数太多”，并确认密码正确。

- 04:03:48 的只读诊断确认实际账号 active、email verified、MFA enabled；API PID 810602、NRestarts=0，cgroup OOM / OOM kill=0，数据库无锁等待。没有读取用户密码、密码哈希、MFA seed 或会话秘密。
- 发生问题的时段有多次登录成功审计，随后出现 RATE_LIMITED。账号对应的当前登录标识窗口 attempts=10、恢复时间为北京时间 **04:06:14**；另一历史窗口已过期。没有清空、调整或绕过限流。
- 使用已有私有 synthetic Observer 账号，实际 HTTPS 登录 200 / 89 ms、控制页 200 / 7 ms、退出 200。公共 `/healthz` 返回 404 是未发布该公共路由；部署工具通过私有 127.0.0.1:3202/healthz 验证 API 200。
- 直接导航到 `/control#vision` 成功进入用户已有管理员会话，证明无需再次提交密码。实际浏览器先显示 Unknown mode / Loading model，模型加载结束后才显示真实账户、角色、退出及相机按钮。
- 九个 STL 共 **22,430,956 B**；现有云带宽 3 Mbps。原 cloud-workspace.js 在初始化账户、相机、会话监测之前等待全部几何模型，导致登录后的工作台显得尚未就绪。文件量和启动顺序是已验证事实，未将理论传输时间当成实测网络耗时。

## 实际改动

仅修改 `apps/web/public/js/cloud-workspace.js`：

- 会话验证和偏好加载完成后，先初始化账户、退出、历史入口、相机和会话监测。
- 几何模型在后台加载；相关滑条、预置动作、夹爪模型与视角工具等待模型完成，防止输入丢失或提前使用未完成模型。
- 模型完成后恢复这些控件、设置初始姿态并适配视角；失败时保留相机与退出功能，显示模型错误。
- 真机控制面板仍等待模型完成，既有 SDK 权限、MFA、限流、短租约和只允许观看的约束未更改。

新增启动回归覆盖“几何始终未完成”和“几何失败”两种场景。实际执行先观察到角色仍为 Unknown mode、退出和相机缺失的 RED，再修复为 GREEN；完整公网业务测试 **133 passed / 0 failed / 0 skipped，28.331 秒**。初始测试夹具缺 requestAnimationFrame 已修正，正式 RED 证据排除了该夹具问题。

## 冻结发布与回退

| 项目 | 实际值 |
|---|---|
| 当前版本 | `/opt/thirdhand-stage/releases/fecd12218feca574` |
| 保留旧版本 | `/opt/thirdhand-stage/releases/cf0013639f4a681d` |
| 文件校验 | 4,613 文件，全量清单和逐文件 SHA-256 均匹配；只变更上述一个前端文件 |
| 归档 SHA-256 | `fecd12218feca5740f6d4297f94576141c3057ef939ac864ee7d6448aced0c6f` |
| manifest SHA-256 | `a6f9ad9db12fcade0eb206f59df1de139fa7c7ef66f3d92105186cf520584adb` |
| 实际审计 | `/var/backups/thirdhand/access-C2h-workspace-20261031/acceptance.json` |
| 部署工具 | `tools/operations/apply_staging_workspace_ready.py`；上传后工具 SHA-256 再校验 |
| 配置与展示站 | cloud.env SHA 保持一致；展示站 index SHA 仍为 `639bb62379c763ebbd4610125cafc3ebff3aa14debb0c3ca2f50ee75d1a478bd` |
| 运行操作 | 仅切换 current 并重启 staging API；未修改 Nginx、数据库、认证配置、端口或 Robot/Vision/Web |

部署健康检查失败时工具会恢复旧版本指向并重启 API。人工回退也只切回保留的 cf0013639f4a681d，不能公开旧无鉴权 SDK / 9983。此次没有 Git commit、push 或 PR。

## 真实浏览器复核

管理员旧会话在排障期间达到既有 15 分钟无操作期限，网页已回到登录页。已请用户这次以默认 Observer 重新登录，避免重复管理员 MFA 步骤；观察员会话仍按既有规则管理，不延长管理员权限。

用户随后明确回复“已用 Observer 登录”。在第二个真实浏览器标签中，模型仍显示 Loading model 时，已显示 Observer 身份、Sign out、Load cameras / Watch camera；之后模型完成加载。相机实际解码得到 640×480、readyState=4。此次验证确认登录后的基础功能不再等待模型下载；不代表视频链路长期稳定，也未启用公网 SDK。[C2g 故障与网络记录](2026-10-31-C2g-camera-change.md) 单独追踪。
