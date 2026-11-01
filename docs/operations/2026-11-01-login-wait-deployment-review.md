# 登录等待反馈：固定部署审阅

状态：候选和本地验证完成，尚未上传或应用。用于修复用户本次“提交后转圈、按钮应变灰并提示已发送”的反馈。源码提交 `bbf1ea0d7395c456e397a176f1dd72f31ca06ae3`；其后包含该修复的 `0a11947` 已通过 [CI #40](https://github.com/Oliveirah007/UIEAclub_ThirdHand_VLA/actions/runs/41289219491)。

## 实际范围

云端 staging 当前 release `4688a5dfdcf76810` → 候选 `dfbca02d47ca7f40`。仅更新：

- `apps/web/public/css/auth.css`
- `apps/web/public/js/auth-page.js`
- `apps/web/public/js/i18n-auth-catalog.js`

4656 件清单不变，其余 4653 件逐字节保留。仅重启 `thirdhand-stage.service`，短暂重连业务页面；不更改数据库、账户、权限、Nginx、端口、展示站或 Ubuntu，不连接 SDK，不发运动。最新 SDK 权限拆分提交 `0a11947` 不包含在这个三文件部署包中。

## 固定文件

准备目录：`.superpowers/sdd/2026-11-01-sdk-source-audit/login-wait-candidate/`。
云端目标目录：`/var/backups/thirdhand/access-login-wait-20261101/`（owner-only）。

| 项目 | SHA256 |
|---|---|
| cloud.delta.json.gz，293365 字节 | 7f697e5f83a085a63d631ed81d3180139ccfbd86c4eaca261e80bd1d64eeddbe |
| 新 manifest | dfbca02d47ca7f4020354567482265c5f2645a76e509a3f82cf4d23641d5aa4e |
| apply_login_wait_cloud.py | ee94e01a8d16bb8d0002d949975492e7453ee5d223b7c067939bafde9cd2e9d8 |
| 旧 manifest | 4688a5dfdcf768109296765b7937fd8bbb47ec22bd27ae4b25a11562590da1f8 |

构建脚本 `tools/deploy/build_login_wait_release.py` 只读取上述 Git 提交，不打包工作区其他任务修改。构建环境 Python3.14.5；安装器 Python3.11，不重新压缩。安装器复用现场 C3f 的摘要绑定保护器，校验 current、完整旧清单、精确三文件范围、保护配置和零活动租约，再备份、原子切换、健康检查；失败恢复旧 release。

## 执行和验收

1. 核对发布未被其他任务改变、无活动控制租约及在途命令；保留当前用户会话，不主动退出用户。
2. 上传固定包和安装器，核对摘要；执行默认 review（不变更），若基线、配置或包不符则停止，不覆盖其他发布。
3. 获准范围内执行 `python3 apply_login_wait_cloud.py --apply`。安装器保留旧目录和 `before-public.json`；健康检查要求原 `explicit-read-only` 模式。
4. 匿名请求核对新登录资源摘要；浏览器核对语言、布局、按钮样式。不为演示进度重复提交真实密码。真实登录需要用户本人完成；已有账号和 MFA 不变。
5. 回退执行 `python3 apply_login_wait_cloud.py --rollback`，不依赖候选包完整，保留数据和原配置。若 current 已被其他任务改变，停止并报告。

本地认证12项、部署包/共用保护器29项通过；本地真实浏览器验证等待中灰色转圈及15秒超时恢复。详情及截图位置见 [实现与验证](2026-11-01-login-wait-feedback.md)。这不是登录网络延迟根因已解决的证据。

部署后，原 C8 三文件修正版云包的旧 manifest 将失效，必须从新 release 重新构建后续 SDK 权限与状态同步候选，不强行应用旧包。最新观察员 SDK 权限仍等待两端固定包、迁移012和独立部署审阅。

## 确认依据

此前批准的 C8 流程要求固定候选审阅后应用；[原审阅](2026-11-01-C8-deployment-review.md)第5行明确“实际服务器变更须审阅固定候选后应用”。本次三文件包不在先前固定清单内，因此提交这个具体范围供确认；无需重新审批已通过的登录视觉设计。
