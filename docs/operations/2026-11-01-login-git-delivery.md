# login分支：源码、资源与功能提交整理

用户在C6部署阶段后新增明确要求：当前阶段完成后更新信息，跟踪运行必要的新文件并推送到现有fork的login分支；以后每个独立功能完成且必要检查通过后自动本地提交；同步详细Markdown实现说明。偏好已保存在根目录`AGENTS.md`，不推导出强推、合并main或自动部署权限。

## 基线与范围

工作目录`D:/claudeworkplace/thirdhand-login`，分支login，原HEAD为24c6f9c。实际fetch后fork origin/main也是24c6f9c；origin仍为`Oliveirah007/UIEAclub_ThirdHand_VLA`。没有rebase、reset工作文件或改动main。新分支采用普通`git push origin login`，最终提交应与远端refs/heads/login逐项核对。

提交按功能整理：

1. `f6f396f`：公网鉴权业务基础，416件路径。包含此前尚未跟踪的账户/MFA/注册审批、数据库/历史导出、媒体授权、设备网关与只读SDK/软件租约守卫、测试/部署模板及详细说明；保留另一聊天原已暂存的27件身份变更。
2. `33ee850`：独立展示站源码、成品媒体与控制登录入口，92件路径。原ZIP缺少可选素材生成脚本，移除不可用命令，正常安装/构建无需该脚本。
3. `51030b4`：个人模型点位UI/API/存储、最小授权SQL、固定应用器/包构建器、测试和实际验收文档。

这三项功能提交已成功普通推送；`git ls-remote`确认远端login为`51030b439819a2d0a8084c4a940bbba06aba9ed4`，main仍为原24c6f9c。本次末尾的文档收尾提交只记录上述已核实结果，再普通推送到同一login；没有创建PR或合并main。

为保持基础提交不提前引用尚未提交的C6路由/面板，第一组保留原暂存server/workspace-pages并使用发布前cloud-workspace快照，逐字摘要与C6包中的beforeHashes一致；工作目录完整新版始终保留，C6提交再纳入最终差异。既有模型插值/夹爪控制能力可独立使用。第一组112个暂存JS模块的相对依赖完整。

## 必要资源与私有数据

- 审阅535件新增/修改路径；URDF和9件STL已经在原main跟踪，网格沿用Git LFS。真实文件不是LFS占位指针。
- 工作台白名单资源无缺失；frame-metadata worker由锁定npm包解析，`npm ci`恢复，不手工复制到public。
- 展示媒体/字体注册表47项文件引用均存在；本次新增最大文件约3.4MB，可普通Git跟踪，无需修改既有LFS规则。
- 公网工作台、identity/storage/edge源码、迁移、依赖锁文件、部署模板、测试与说明纳入提交；node_modules/虚拟环境、私钥/证书、真实管理员名单、数据库、日志/outbox、导出内容和`.superpowers`运行证据不提交。
- 历史诊断工具不再写死真实用户地址，改由维护环境中的`THIRDHAND_DIAG_OWNER_EMAIL`提供，并对SQL字符串做转义；不记录地址或密码。实际初始管理员名单仍在私有文件内，不进入源码。

## 验证

- C6冻结9件发布源码及3件工具/SQL摘要仍全部匹配；相关Node348/348和部署Python5/5的已通过证据保留，未因Git整理修改这些源码。
- 展示站2/2集成测试、TypeScript构建和Vite生产构建通过；正常构建输出在ignored dist，不提交。
- 私有路径/完整私钥块/超限文件审核未发现问题；必要资源检查无缺失；各提交暂存格式检查通过。最终完整交付快照115个新增/修改JS模块的相对依赖全部存在，剩余未跟踪/未提交文件仅下面9件候选；暂存区为空。
- 未宣称全仓测试全部通过；已记录的旧网页/标定失败、真实运动与相机稳定性门禁不因Git提交改变。

## 保留的未完成工作

相机采集时间候选尚未实际部署/验收，本轮不替其他任务提交。完整保留9件路径：

- `drivers/xvisio/README.md`
- `drivers/xvisio/native/xvisio_rgbd_stream.cpp`
- `drivers/xvisio/native/capture_timing.hpp`
- `drivers/xvisio/src/xvisio_stream.py`
- `services/vision/python/camera_bridge_with_frames.py`
- `services/vision/src/config.js`
- `services/vision/src/server.js`
- `tests/native/xvisio_capture_timing_test.cpp`
- `tests/python/vision_service/test_xvisio_capture_timing.py`

因此交付后工作区仍有这组修改，不把它误报成“全仓干净”。普通功能提交和线上C6部署是两件事：此次Git整理不改变服务器、Ubuntu、设备证书或机械臂状态。

后续CI核对发现上面9件中的`services/vision/src/config.js`和`server.js`实际上属于已完成的私有相机接口，并非时间采集候选；本次拆分遗漏已在[CI修复](2026-11-01-ci-repair.md)纠正。其余7件仍保留。此处保留首次交付时的原始范围，不能将遗漏解释成这些接口不需要跟踪。
