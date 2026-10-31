# C7 双布局复用与启动优化

## 范围和状态

按用户批准的A–E实施，并以用户后续指定的Git提交复用要求为准。
本次是代码、资源、测试和部署候选交付；截至本记录编写时，staging仍为C6，未上传或应用C7。
与XVisio采集时间相关的七个并行任务文件没有纳入此交付。

## 原版复用

来源主仓库提交`372ac80a98e279e85bd25dfe8f219b399b97cb80`。
`git show`直接读取以下原始字节，`.gitattributes -text`保留换行，不格式化快照：

| 交付文件 | 原路径 | SHA-256 |
|---|---|---|
| `apps/web/public/classic.html` | `apps/web/public/index.html` | `f61a58529141ac8d66e99d9f81695aa6bb775b704be7eafb1ff5b839c4dc8294` |
| `apps/web/public/css/classic-source.css` | `apps/web/public/css/style.css` | `1dd9790284eaf2515624f5f2c47ae5bb6135473443eb468d3041802d1f2481de` |

保留原DOM层次：`#app > #viewport`，工具和连接栏位于viewport，右侧抽屉仍在body下。
`classic-shell.js`复用原抽屉开合/章节折叠逻辑，新增紧凑账户、相机、运行记录和教程入口，账户设置用独立对话框。
`workspace-layouts.css`仅补充这些新增控件、启动遮罩和选择器，不覆盖原画布、抽屉几何或九种配色。
新版继续使用原`workspace-shell.js`，并未删除。

云端不执行旧`main.js`，也不启动其裸SDK/WebSocket、麦克风、Dummy跟随流程。
模型、账户、管理员连接和相机继续由当前鉴权适配器提供；权限由服务器判断。
经典页的个人点位复用C6接口与插值控制，不产生真机指令。
旧TCP标定入口在云端保持不可用提示，不引入未授权的独立标定连接。

## 偏好、数据库与首屏

迁移011新增`auth.user_preferences.layout_id`（默认`workspace`，枚举workspace/classic）和
`classic_theme_id`（默认`deepspace`，原九种主题枚举）。现有theme_id仍是新版light/dark。
不会修改账户角色、密码、会话、运行记录或控制权；旧客户端漏传新字段时保留数据库值。
回退源码保留新列及已保存偏好。

`workspace-bootstrap.js`用一个非锁定查询读取当前用户显示名及偏好；仅在已鉴权`/control`响应中注入安全JSON。
不把用户身份放在localStorage、URL或静态缓存中。
服务器据layout_id选原始经典模板或新版模板，首屏即带语言、布局、主题和模式。
浏览器先完成轻量外壳再显示页面，避免错误布局先闪现；切换布局保存成功后reload，由服务器选择新文档。
外观客户端按revision串行保存连续操作，保留原账户隔离和旧请求epoch防护。

## 启动、相机和缓存

`cloud-workspace.js`只引导`workspace-startup.js`；Three.js不再是入口的静态依赖。
账户摘要/头像、退出、设置、相机控件和会话监测先挂载，完整资料和Three模块/模型分别异步加载。
模型输入在几何就绪前禁用，失败显示重试；超过20秒给出慢加载提示。
通用账户/会话请求含响应体读取最多12秒，超时中止传输；仅实际401未鉴权进入退出流程。
完整资料加载失败仍显示已鉴权显示名，可在账户页重试。
LiveKit客户端仅点击观看时加载，失败可重试；保持原短期授权/撤销策略。

受保护资源统一为`/control-assets/v<32位内容摘要>/…`，摘要覆盖静态模块/模型依赖图。
同一不可变进程/发布中计算一次；开发修改资源后必须重启预览，不能在相同版本URL下替换内容。
浏览器可跨刷新/登录复用不含用户数据的资源，`Vary`只有Accept-Encoding，避免Cookie变更导致整包重下。
匿名/撤销会话的网络请求仍401（包括条件请求），错误内容版本404；HTML和动态API保持no-store。
GLB有固定预压缩gzip、正确长度/Content-Encoding/ETag；不发布公共CDN缓存。
已缓存源码/模型可保留在浏览器；它们不包含身份或调用SDK的授权。

## 模型资源与依赖

| 内容 | 字节数 |
|---|---:|
| 原9件STL | 22,430,956 |
| 原STL gzip级别3合计 | 8,249,354 |
| 网页GLB | 3,050,660 |
| 网页GLB gzip | 1,918,246 |

原STL和URDF不改。全部448,604三角面顺序/绕序及float32顶点位相同，无减面、坐标量化或Meshopt滤波。
共享位置索引+Meshopt压缩减少传输；法线按面重建，不声称原STL法线属性逐位相同。
仍由原URDF驱动骨架、轴、限位、安装变换、夹爪联动和0.17334米TCP偏置。
`compact-model.test.js`解码并展开全部索引，逐三角比较原STL顶点字节，校验哈希、包围盒和gzip。

构建工具`tools/assets/build_web_robot.py`、`pack_web_robot.cjs`；输入/输出摘要见build-report.json。
GLB和gzip均为Git LFS载荷。Three r163加载器/工具匹配本地核心，Meshoptimizer为0.22.0，运行时均本地提供并附MIT许可证。
开发依赖和锁文件更新，线上无需重新npm安装；CSP仅增加WebAssembly编译许可`wasm-unsafe-eval`，不开放JavaScript unsafe-eval。

## 本地与云端运行

新clone执行`git lfs pull`和`npm ci`，使用Node24、PostgreSQL17及独立测试数据库。
业务启动沿用PUBLIC_ACCESS.md中的HTTPS/Secure Cookie和私有env配置。
新环境标准迁移器会应用011；当前staging只能在批准C7具体变更后由root操作器应用011，不给业务角色DDL权限。
学校网络、媒体服务和Ubuntu服务无需因本轮外观/加载变化重新配置。

本机验收辅助代理仅监听loopback，用一次性测试库及模拟用户；它不是生产Cookie/TLS安全证明，也没有连接真实相机或SDK。
线上验收必须用真实HTTPS和本人会话另行完成。

## 验证、测量与限制

已执行：原始字节/DOM结构和SDK隔离、双布局保存/跨会话读取、模型完整性、延迟/失败的Three与profile、授权资源缓存边界、相机库延迟加载、账户隔离、修复快速主题/语言保存冲突。
浏览器验证原右侧抽屉和章节开合、旧版九配色选择、语言保留、账户入口及C6模型点位入口；未发送SDK连接或运动请求。
本地公网业务320/320、相关网页/模型42/42、固定部署包边界Python8/8通过；源码边界审计ready、Git差异空白检查通过。
远端Linux CI以对应交付的实际Actions结果为准；不把Windows旧夹具权限错误改为跳过。

本地冷加载新版测得外壳567ms、模型1261ms；另一轮经典版冷加载外壳514ms、模型1188ms。
最终固定候选重新登录后，经典页测得外壳166ms、模型510ms，45件受保护静态资源均缓存命中、传输0字节。
模拟仅模型3Mbps且Three额外延迟3秒时，外壳379ms、模型8824ms；模型实际下载5118ms。
这些为开发机loopback测量，不能代表公网、学校网络或真实视频时延。
完整动态认证POST此前转圈的原因没有取得现场耗时证据，不能据本轮资源优化宣称所有登录问题已消除。

浏览器工具的390px视口设置未生效，实际DOM宽度仍1592px，已恢复设置；手机断点实际浏览器验收仍待完成，不用桌面截图冒充手机结果。
现场相机稳定性/采集UTC、独立物理停止、真机运动/点位、正式教程合并和正式生产发布均仍按既有清单继续。
