# 网页抓取与实测 TCP 接通

主页面：选择视觉目标 → 一键抓取 → 获取深度 → 坐标规划与路径检查 → 张开 → 预接近 → 刷新目标深度 → 接近 → 闭合 → 抬升保持。没有分步“下一步”按钮，也不会在成功后自动松爪。

主页面顶部 TCP 标定入口：`/tcp-calibration.html`。标定仍要求 8 个不同角度的拟合姿态与 3 个独立验证姿态；保存 pending 不会自动激活。确认激活或回滚后，下一次一键抓取自动读取对应的 `T_flange_grasp_tcp` 完整矩阵。正在执行的会话固定使用启动时的版本，网页显示版本哈希和偏移。

无激活版本时沿用原实验近似 TCP +X 60 mm，以及保持基坐标高度的水平退让 60 mm。实测版本默认水平退让为 0，避免将原经验修正再次叠加；如仍需要退让，单独配置 `apps/web/configs/web-grasp.json` 中 `calibratedForwardBackoffM`。这不是精度或碰撞认证。已激活版本损坏、未通过验证或坐标策略不同会拒绝启动，不会静默退回近似值。

## 端口与所有权

浏览器 HTTP/WS → Web 9983 → 既有 Robot 3000。抓取和标定反馈都经同一个网页转发；不在网页服务打开 CAN、不创建新 SDK 控制进程、不修改阻尼。主线 Robot 服务当前没有示教接口，页面会禁用进入拖动按钮；使用现有控制方式摆位，待姿态静止保持后，确认「已静止」再采样。不要强行扳动带保持力矩的机械臂。

采样需要健康、新鲜、法兰规范化的反馈，并通过连续一秒稳定窗口。运动期间禁止采样、激活/回滚和示教等修改；软件停止仍可请求。失败/停止原因直接显示；停止未确认时保持互斥，需现场检查。流程完成仅表示反馈与控制链结束，实物是否成功抓住需现场观察。

## 启动配置与数据

`configs/runtime/manual-control.json` 已配置 `WEB_GRASP_CONFIG`、`TCP_CALIBRATION_ENABLED`、统一 `TCP_CALIBRATION_ARTIFACT_ROOT` 和 Python 求解器。统一视觉配置使用新的 `configs/vision/sdk-tool-frame-policy.json`、`handeye-flange-normalized.json`；视觉服务自动启动已有只读状态转发器。`THIRDHAND_ALLOW_NUMERICAL_HANDEYE=1` 只允许既有数值标定投影，不把物理验证字段改成 passed。

新证据文件使用仓库相对路径及本次主线 SDK/生产者文件哈希。手眼矩阵没有重新估计，记录了原证据哈希；原 `configs/vision/evidence/deployment_20261006/` 不变。若 SDK 或生产者文件变更，哈希检查会失败，应核查坐标语义并重新绑定证据，而不是绕过检查。旧策略绑定的 TCP 候选不能直接当作新策略候选使用。

运行数据保存在被 Git 忽略的 `runtime/tcp-calibration/`，包括不可变会话、候选、pending 指针、active-manifest 和上一版本。抓取审计在 `runtime/web-grasp/sessions/`。更新部署时应保留该机器的 runtime 数据，但不应提交到 Git。页面刷新和连接恢复会读回服务器当前状态。

需要重新标定或更正测量信息时，展开第 0 关的「重新标定 / 更正测量信息」，明确确认后点击「归档本次，开始新标定」。旧会话与样本保留，active/pending TCP 不修改；新会话需重新填写测量信息并逐项确认。该操作要求状态有效、静止且不处于示教中。服务器重启也能恢复归档后的待开始状态。

求解与换算结果绑定调用开始时的会话及 revision；期间删除、采样、结束或重置会话，旧异步结果将被拒绝。软件停止期间网页显示「正在停止，等待确认」并保留控制权；确认失败则保持「状态不确定」。深度对准的停止结果也传递到整体抓取流程。Robot 3000 上游断线会关闭对应转发连接，标定自动重建只读连接；抓取在下一次显式启动时重连。所有重连都不启用硬件、不改变模式，也不自动恢复或重放动作。

## 离线验证与上线边界

`tests/node/web/grasp-tcp-e2e.test.js` 使用真实网页路由、代理、WebSocket 客户端、抓取协调器和标定状态源；仅机械臂/视觉外部 IO 为本机模拟。覆盖 HTTP 目标选择到抬升、实测偏移、状态阶段、标定反馈握手及缺失示教。Python 求解器与几何/存储/UI/所有权测试另行覆盖。

本次只在隔离分支完成代码和离线验证，未部署远端、未发实机动作、未实际激活标定。远端需要更新同一分支并重启既有 Web/视觉服务才能使用新入口；不能仅复制 HTML。实机 TCP 测量、夹爪接触和运动空间应由现场操作者确认。

## 本轮审查与验证

独立只读审查针对主线 `de1f08e` 到实现 `775ad7b`，指出五个重要问题：停止确认的所有权竞争、深度子流程的不确定状态丢失、异步求解提交竞争、无法开启第二次标定、保留连接无法恢复。全部由实现者补充失败回归测试后修复；未进行第二轮审查，也未连接真实设备。

验证命令（在本分支仓库根执行）：

```sh
PYTHON=/path/to/python-with-numpy node --test tests/node/web/grasp-*.test.js tests/node/web/tcp-calibration-*.test.js tools/frames/test_canonical_robot_client.js tests/node/vision_service/projected-state-route.test.js
TMPDIR=/private/tmp PYTHON=/path/to/python-with-numpy node --test --test-skip-pattern='one-click restores a missing listener|repair refuses a lookalike entry' tests/node/*/*.test.js tools/frames/test_canonical_robot_client.js
uv run --system-certs --no-project --with pytest --with numpy --with websockets --with pyyaml --with ikpy --with scipy --with opencv-python-headless --with norfair --with python-socks python -m pytest -q tests/python/tcp_calibration tests/python/vision_service/test_projection_frames.py tests/python/vision_service/test_projection_runtime.py tests/python/vision_service/test_projection_snapshot.py tests/python/vision_service/test_handeye_projection.py tests/python/fixed_tcp_demo tests/python/robot_service
```

Node 可跨平台回归 427 项通过，排除的两个旧启动器测试依赖 Linux `/proc`，在本次 macOS 环境不适用；这不是 Linux 全量验证。Python 初次回归缺少 `norfair` 与 SOCKS 依赖，补足隔离测试环境后 94 项通过；没有修改生产 Python 依赖或源文件来绕过这些错误。

本轮决策与限制：只接既有网页转发，不新增 CAN/SDK 控制所有者；不重新估计手眼矩阵或宣称实测精度/阻尼通过。实际部署可移植性与物理抓取均留待已授权的实机验证，误把离线通过当作实机通过会有位置误差及碰撞风险。
