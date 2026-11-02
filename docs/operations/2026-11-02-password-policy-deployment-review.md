# 注册密码规则固定部署审阅

状态：本地完成，23项认证测试通过；固定包已构建并核验，尚未上传或应用到staging。

## 行为与范围

新注册和重置密码统一要求8–128个Unicode字符、最多512字节，至少一个大写英文字母A–Z及一个小写英文字母a–z；数字、符号可选。两密码框右侧实时说明缺失项，下方显示完整要求，保留中英文切换。旧密码仍可登录，不改用户现有密码或强制重置。登录占位哈希输入保证同时含大小写，避免初始化偶发不符合新规则。

源提交：`8f09766065e90928d047d24d0a26fe5f73a91447`。仅更新以下五件：

| 文件 | 新SHA256 |
|---|---|
| apps/web/public/js/auth-page.js | 0fc25f7217fd686340bb2f962324b5cfdffb971fe15bcafa2d471fb4032785f7 |
| apps/web/public/js/i18n-auth-catalog.js | 7b82ff67c9bf7ad4cb1fa4d9aebee2b00d3b1991a3063211a0bc72e2ca5ebf22 |
| apps/web/public/reset-password.html | 7ceef806b29f5a8d20cfad43156a110c8dc0f3c5946492e1c83899ab11f0ffa9 |
| platform/identity/src/accounts.js | dcf426400b4bc1cab52598efc6961fe5ea28ea296f7798ac003f13550304e2d0 |
| platform/identity/src/passwords.js | db213e2749bf10f6b56f6abd2a4e041e9d44d683e22bfe452835278601492d05 |

不改数据库结构、账号角色、MFA、SDK、Ubuntu、诊断开关、Nginx或端口。仅重启staging业务API，可能短暂重连页面和设备通道；无SDK初始化、运动或真实测试邮件。

## 固定包与准入

- 本地：`.superpowers/sdd/2026-11-01-sdk-source-audit/password-policy-candidate/cloud.delta.json.gz`，295171字节。
- 包SHA256：`31d375891a8606241d9567a48ec5a2b1279bfc97b683af4bf7a8b6bda61d7490`。
- 原发布：`/opt/thirdhand-stage/releases/f72e61d85009b7ea`；清单摘要`f72e61d85009b7eafb8f9447c6638dde0968dde84eec9e30e6991db931b9bf44`。
- 新发布：`/opt/thirdhand-stage/releases/e3f0176566d900ed`；清单摘要`e3f0176566d900ed4ee3c576778df465e02de7abbc2284c245b804e93f526877`。
- 总清单仍4658件，只有上述5件替换，其余4653件逐字节保留。已核对源提交父版本的5件SHA与安装基线一致，不夹带其他未发布功能。包从固定Git提交构造，不读取工作区相机改动。
- 云端上传／备份目录：`/var/backups/thirdhand/access-password-policy-20261102`，0700；包0600。此目录本次尚未创建。

应用采用与上一轮相同的已核验部署保护器和人工固定规程，不直接复用仅允许其他文件范围的旧安装器。执行前检查实际current、4658件完整摘要及服务配置、cloud.env和展示站保护摘要；任何漂移停止，不覆盖其他发布。检查活动租约、在途命令均0，设备SDK断开；持有部署锁和零租约准入后备份。

复制旧发布到新绝对路径，只应用包内精确5件及新manifest；全清单校验通过后原子切换current，仅重启thirdhand-stage.service。健康检查仍须返回explicit-read-only，既有两个诊断开关保持0。验证匿名页面资源与固定摘要、双语密码提示；不由代理设置真实用户密码。

失败回退：在零租约和SDK断开下确认current仍为本候选、旧发布完整，原子切回f72e61d85009b7ea并重启业务API。保留新旧发布、用户数据及配置。旧密码验证不受新策略限制，回退仍能登录新建8位混合大小写密码；旧创建/重置流程恢复原12位要求。若current已被其他任务改变则停止。

## 验证与批准依据

23项本地认证测试全部通过，包括真实隔离PostgreSQL的8字符注册／邮箱激活／登录、重置拒绝纯大写且不消耗有效令牌、重置后旧密码失效；前端中英文实时提示、7/8字符、纯数字/纯大写/纯小写拒绝、Unicode上限、旧版密码哈希验证。初次受限HTTP测试EACCES，允许本机访问后通过，测试数据库已停止。未声称本次已完成线上验收。

此固定包改变线上认证规则，超出已批准的SDK诊断包。按已批准的[C8部署流程](2026-11-01-C8-deployment-review.md)“实际服务器变更须审阅固定候选后应用”，需批准以上5件、私有备份目录、原子切换、单服务重启与必要回退后再执行。
