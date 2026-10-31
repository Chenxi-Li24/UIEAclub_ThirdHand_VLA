# Public showcase source mapping

Status: source ownership unconfirmed. The user explicitly deferred showcase hero/navigation changes on 2026-10-30: "不清楚先不改". Do not modify the production static showcase or continue searching unrelated repositories for this task. Login and protected workspace implementation continue independently.

2026-10-31复核：用户曾要求从宝塔文件增加入口，但检查静态目录和 `thirdhand-deploy-1792915217453.zip` 后，只发现构建产物，没有React/JSX/TSX原始源码或package.json。用户随后明确要求“展示页面如果没有源码就不要改了”。已停止该部分，清除本轮未发布的入口草稿；服务器首页和资源均未修改。首次检查首页仍为1348字节，SHA256为 `639bb62379c763ebbd4610125cafc3ebff3aa14debb0c3ca2f50ee75d1a478bd`。

| Item | Evidence / state |
|---|---|
| Public domain | `uiea-thirdhand.com` |
| Production static directory | `/www/wwwroot/uiea-thirdhand-static`, from read-only Baota inspection on 2026-10-29 |
| Current control repository base | `24c6f9c470e19647a3e22880a6ffa493ebe7765a`, canonical Chenxi-Li24 main |
| Existing control source | `apps/web/public/index.html`; this is the robot workspace, not confirmed showcase source |
| Showcase source repository and commit | Not yet supplied/verified |
| Hero and top navigation source files | Not yet verified |
| Production build/deploy command | Not yet verified |
| Backup/rollback | Must be prepared from current server files before actual deployment; no backup claimed yet |

If this deferred change is resumed later, both the first showcase screen and top navigation should link to the same protected workspace entry `/control` (English label `Open Control`, Chinese label `进入控制台`). Authentication determines the next route; neither link connects SDK or claims a control lease. Preserve language/theme selections using the shared validated preference mechanism. These links are not part of the current implementation acceptance.

Do not patch bundled/minified production JavaScript to approximate a source change. Before final showcase acceptance, identify the owning source repository, source files, build command and deployment commit, then add and test both links there. Vendored third-party home pages in this repository are not evidence that they own the public showcase.
