# 部署分支整合记录（2026-10-07）

## 范围与历史
本轮只在独立工作树整理源码，不改运行目录、不停止服务、不构造 SDK、不发送运动。
旧部署分支已获批准创建本地进度提交 `727aa2cac9d9d5d69a8c8daa17d8b0626a6a7c1c`。
整合基线为 `7ee804ce54f403a2603c0ef213ce7805ad3f29c6`；使用普通双亲合并。
整合提交、推送、两级 PR 合入、部署切换和删除旧分支都仍需对应确认。

工作树：`/home/nieqingcao/ThirdHand/worktrees/deployment-to-main-20261007`。
原运行目录及其备份、普通日志、辅助文件保持原状，未提交这些运行杂项。

## 模块处理
- `apps/dummy` 的正式源码、配置、测试保持远端新版：YuNet、FACE/BODY、连续跟随、J1 50°/s 策略和网页启停。
- 旧 Dummy 独立收纳到 `apps/dummy/experiments/deployment_20260915`，包名为 `dummy_legacy`，不默认启动。
- 旧网关仅保留在实验目录；它的 lease、旧 step 限值与 Mink/全臂实验不是正式跟随策略。
- 轴响应校准原文保存在实验目录 `configs/calibration/axis-response.json`，不自动加载。
- 固定 TCP 演示移到 `apps/fixed_tcp_demo`，后续补入 e1c0e9b/179fec2/522cd2b：CLI 和网页都请求 3000 唯一 SDK 所有者，不再自行创建 SDK。
- dry-run 只请求现有 3000 执行不下发运动的规划，仍需要已连接的状态与 IK，不能当作完全离线测试；本轮使用 FakeArm。
- 被新提交删除的直接 SDK 入口归档到 `History/fixed-tcp-before-port3000/arm.py`；不默认加载。
- 机器人服务保留新版实时反馈、SDK 速度模式，同时保留部署独有的预抓取与精度参数接口。
- Web 同时保留新版 Dummy 接口和可选抓取接口；未配置或缺少实现时返回不可用，不宣称能自主抓取。

## 追加批准的直接依赖
核对时发现 manual-control 仍调用项目外代码，用户随后批准迁入直接依赖：
- `deployments/grasp-prototype-1894746-20261004/tools/vision` 的 RGB-D 导出、逐帧投影与几何质量代码移入 `services/vision/python`。
- 只读状态 relay 与坐标语义工具移入 `services/vision/src`；它们不能发送机器人命令。
- Meituan 独立页面由 `worktrees/cyb_branch/meituan/apps/web` 移入 `apps/meituan`，使用同一项目内的 `meituan-web` profile。
- Meituan 电池识别复用 3100 的 CameraProcess 和现有模型；1035 是该进程的额外只读画面入口，不是第二个相机所有者。
- Meituan 页面直接需要的 Skill、点位、schema、模型适配与配置保留在 `skills/manipulation/meituan_battery_pnp` 与 `configs/meituan`。
- 原手眼文件与 SDK-tool-frame policy 原文保存于 `configs/vision/evidence/deployment_20261006`，没有修改数值、物理批准状态或证据原文。
- 原部署 URDF 与正式 URDF 的 SHA-256 相同：`0e52a6ed086e87b2d3dc24391874ab433e7e9cc33b6b0fc995370cf9e37dea86`。
- formal profile 不再从 `../deployments` 或 `../worktrees` 导入运行代码；一键启动默认使用本项目内的两套网页。
- 用户选择本轮 Meituan 只迁入源码、不启用运动：1034 保留识别/状态/IK 预览/软件停止，拒绝运动直传、夹爪、Skill 执行确认和 HTTP 主动视角启动。旧环境变量不能单独开启；未来须先补齐 3000 的跨客户端路线占用再另行批准。

## 明确未完成
1. 四个 runtime-confidence 契约引用 snapshot/main 都不存在的 API，现保存在 `tests/pending/vision`。正式网页置信度协议尚未接通，不能说其已生效。
2. `kinematic_preview.js` / `preview_ik.py` 保留为离线模块，但 BottleGrasp 的完整运动预览 route 尚未接线。
3. 可选 `WEB_GRASP_CONFIG` 接口缺少默认 `apps/web/src/grasp` 实现，未设置配置时不可用。
4. 非 lift-only 的监督会话没有 buildPlan，可能返回 `supervised_plan_unavailable`；默认 profile 不开启 lift-only。
5. 只读投影的旧 policy 绑定旧源码和运行库哈希。迁移后必须单独复核并重新绑定证据；不得绕过哈希检查或改成已物理批准。
6. Meituan 模块源码迁入不代表当前 3000 已支持其所有旧 command options；只读画面与假后端测试不能替代真实机械臂兼容验证。
7. 不把归一化手眼数值、URDF 候选 GRIP 或虚拟深度描述成已经做过现场物理误差验证。

## 验证与后续门槛
进度文件机器可读清单见 `deployment-file-inventory-20261007.json`；
追加直接依赖 85 个文件的来源、去向及原文哈希见
`external-dependency-inventory-20261007.json`。原文哈希用于追溯，不表示适配后的文件字节相同；两个原始校准证据文件要求字节保持一致。

本轮基线：Node 182 项，Python 162 项及 58 子测试。
整合运行过 Node、正式 Python、新版 Dummy、FakeArm、逐帧投影和源码边界审计；结果以整合提交前最后一轮为准。
资源验证对清单逐文件检查大小及 SHA-256，不导入 SDK、不运行模型推理、不访问相机。
最终复核和测试证据见 `INTEGRATION_REVIEW_20261007.md`。干净 CI 使用
`tools/assets/requirements-test.txt` 与单独的 CPU Torch 安装步骤；正式 Vision/runtime 清单补齐 IKPy。
任何实机验证或服务切换仍须重新获得停止服务、硬件托稳与现场看护授权。
运行指南仍以 `docs/RUN_GUIDE.md` 为主；部署切换前先核对本记录的未完成项。

## 147 个进度文件的逐项去向
A 为新增，M 为已有文件修改。来源原文均可从 727aa2c 恢复。
迁移/适配后的文件不保证字节等同；数值校准与原始证据保持原文。
整合不是整目录“本地优先”，正式 Dummy 使用远端新版，旧版本在独立实验包中。

| 状态 | 来源路径 | 整合路径 | 处理结果 |
|---|---|---|---|
| M | `README.md` | `README.md` | 合并/更新说明 |
| M | `README_CN.md` | `README_CN.md` | 合并/更新说明 |
| M | `apps/README.md` | `apps/README.md` | 合并/更新说明 |
| A | `apps/dummy/apps/calibrate_axis_response.py` | `apps/dummy/experiments/deployment_20260915/apps/calibrate_axis_response.py` | 隔离旧实现；正式入口保持新版 |
| A | `apps/dummy/apps/calibrate_touch_r1_gimbal.py` | `apps/dummy/experiments/deployment_20260915/apps/calibrate_touch_r1_gimbal.py` | 隔离旧实现；正式入口保持新版 |
| A | `apps/dummy/apps/diagnose_follow_window.py` | `apps/dummy/experiments/deployment_20260915/apps/diagnose_follow_window.py` | 隔离旧实现；正式入口保持新版 |
| A | `apps/dummy/apps/run_1023_gateway.py` | `apps/dummy/experiments/deployment_20260915/apps/run_1023_gateway.py` | 隔离旧实现；正式入口保持新版 |
| A | `apps/dummy/apps/run_dume_follow_touch_r1.py` | `apps/dummy/experiments/deployment_20260915/apps/run_dume_follow_touch_r1.py` | 隔离旧实现；正式入口保持新版 |
| A | `apps/dummy/apps/run_follow_stack.py` | `apps/dummy/experiments/deployment_20260915/apps/run_follow_stack.py` | 隔离旧实现；正式入口保持新版 |
| A | `apps/dummy/apps/run_head_body_follow.py` | `apps/dummy/experiments/deployment_20260915/apps/run_head_body_follow.py` | 隔离旧实现；正式入口保持新版 |
| A | `apps/dummy/apps/visualize_head_body_window.py` | `apps/dummy/experiments/deployment_20260915/apps/visualize_head_body_window.py` | 隔离旧实现；正式入口保持新版 |
| M | `apps/dummy/configs/dum_e_touch_r1.yaml` | `apps/dummy/experiments/deployment_20260915/configs/dum_e_touch_r1.yaml` | 隔离旧实现；正式入口保持新版 |
| A | `apps/dummy/logs/axis-response.json` | `apps/dummy/experiments/deployment_20260915/configs/calibration/axis-response.json` | 隔离旧实现；正式入口保持新版 |
| M | `apps/dummy/src/dummy/director.py` | `apps/dummy/experiments/deployment_20260915/src/dummy_legacy/director.py` | 隔离旧实现；正式入口保持新版 |
| A | `apps/dummy/src/dummy/distance_aware_follow.py` | `apps/dummy/experiments/deployment_20260915/src/dummy_legacy/distance_aware_follow.py` | 隔离旧实现；正式入口保持新版 |
| A | `apps/dummy/src/dummy/dume_touch_r1_follow.py` | `apps/dummy/experiments/deployment_20260915/src/dummy_legacy/dume_touch_r1_follow.py` | 隔离旧实现；正式入口保持新版 |
| A | `apps/dummy/src/dummy/follow3d/__init__.py` | `apps/dummy/experiments/deployment_20260915/src/dummy_legacy/follow3d/__init__.py` | 隔离旧实现；正式入口保持新版 |
| A | `apps/dummy/src/dummy/follow3d/contracts.py` | `apps/dummy/experiments/deployment_20260915/src/dummy_legacy/follow3d/contracts.py` | 隔离旧实现；正式入口保持新版 |
| A | `apps/dummy/src/dummy/follow3d/controller.py` | `apps/dummy/experiments/deployment_20260915/src/dummy_legacy/follow3d/controller.py` | 隔离旧实现；正式入口保持新版 |
| A | `apps/dummy/src/dummy/follow3d/depth_estimator.py` | `apps/dummy/experiments/deployment_20260915/src/dummy_legacy/follow3d/depth_estimator.py` | 隔离旧实现；正式入口保持新版 |
| A | `apps/dummy/src/dummy/follow3d/diagnostics.py` | `apps/dummy/experiments/deployment_20260915/src/dummy_legacy/follow3d/diagnostics.py` | 隔离旧实现；正式入口保持新版 |
| A | `apps/dummy/src/dummy/follow3d/distance_policy.py` | `apps/dummy/experiments/deployment_20260915/src/dummy_legacy/follow3d/distance_policy.py` | 隔离旧实现；正式入口保持新版 |
| A | `apps/dummy/src/dummy/follow3d/handeye_projector.py` | `apps/dummy/experiments/deployment_20260915/src/dummy_legacy/follow3d/handeye_projector.py` | 隔离旧实现；正式入口保持新版 |
| A | `apps/dummy/src/dummy/follow3d/mink_backend.py` | `apps/dummy/experiments/deployment_20260915/src/dummy_legacy/follow3d/mink_backend.py` | 隔离旧实现；正式入口保持新版 |
| A | `apps/dummy/src/dummy/follow3d/target_projector.py` | `apps/dummy/experiments/deployment_20260915/src/dummy_legacy/follow3d/target_projector.py` | 隔离旧实现；正式入口保持新版 |
| A | `apps/dummy/src/dummy/follow_loop_state.py` | `apps/dummy/experiments/deployment_20260915/src/dummy_legacy/follow_loop_state.py` | 隔离旧实现；正式入口保持新版 |
| A | `apps/dummy/src/dummy/gateway_1023.py` | `apps/dummy/experiments/deployment_20260915/src/dummy_legacy/gateway_1023.py` | 隔离旧实现；正式入口保持新版 |
| A | `apps/dummy/src/dummy/head_body_controller.py` | `apps/dummy/experiments/deployment_20260915/src/dummy_legacy/head_body_controller.py` | 隔离旧实现；正式入口保持新版 |
| A | `apps/dummy/src/dummy/head_body_visualizer.py` | `apps/dummy/experiments/deployment_20260915/src/dummy_legacy/head_body_visualizer.py` | 隔离旧实现；正式入口保持新版 |
| A | `apps/dummy/src/dummy/image_jacobian_servo.py` | `apps/dummy/experiments/deployment_20260915/src/dummy_legacy/image_jacobian_servo.py` | 隔离旧实现；正式入口保持新版 |
| A | `apps/dummy/src/dummy/mink_lookat_controller.py` | `apps/dummy/experiments/deployment_20260915/src/dummy_legacy/mink_lookat_controller.py` | 隔离旧实现；正式入口保持新版 |
| A | `apps/dummy/src/dummy/person_lock_tracker.py` | `apps/dummy/experiments/deployment_20260915/src/dummy_legacy/person_lock_tracker.py` | 隔离旧实现；正式入口保持新版 |
| A | `apps/dummy/src/dummy/rgbd_target.py` | `apps/dummy/experiments/deployment_20260915/src/dummy_legacy/rgbd_target.py` | 隔离旧实现；正式入口保持新版 |
| M | `apps/dummy/src/dummy/robot_ws_client.py` | `apps/dummy/experiments/deployment_20260915/src/dummy_legacy/robot_ws_client.py` | 隔离旧实现；正式入口保持新版 |
| M | `apps/dummy/src/dummy/touch_r1_adapter.py` | `apps/dummy/experiments/deployment_20260915/src/dummy_legacy/touch_r1_adapter.py` | 隔离旧实现；正式入口保持新版 |
| A | `apps/dummy/src/dummy/touch_r1_gimbal_mapper.py` | `apps/dummy/experiments/deployment_20260915/src/dummy_legacy/touch_r1_gimbal_mapper.py` | 隔离旧实现；正式入口保持新版 |
| A | `apps/dummy/src/dummy/virtual_3d_target.py` | `apps/dummy/experiments/deployment_20260915/src/dummy_legacy/virtual_3d_target.py` | 隔离旧实现；正式入口保持新版 |
| M | `apps/dummy/src/dummy/vision_service_tracker.py` | `apps/dummy/experiments/deployment_20260915/src/dummy_legacy/vision_service_tracker.py` | 隔离旧实现；正式入口保持新版 |
| A | `apps/dummy/src/dummy/visual_servo_gaze.py` | `apps/dummy/experiments/deployment_20260915/src/dummy_legacy/visual_servo_gaze.py` | 隔离旧实现；正式入口保持新版 |
| A | `apps/dummy/src/dummy/workspace_guard.py` | `apps/dummy/experiments/deployment_20260915/src/dummy_legacy/workspace_guard.py` | 隔离旧实现；正式入口保持新版 |
| A | `apps/dummy/src/dummy/yolo_person_detector.py` | `apps/dummy/experiments/deployment_20260915/src/dummy_legacy/yolo_person_detector.py` | 隔离旧实现；正式入口保持新版 |
| A | `apps/dummy/tests/test_1023_gateway.py` | `apps/dummy/experiments/deployment_20260915/tests/test_1023_gateway.py` | 隔离旧实现；正式入口保持新版 |
| A | `apps/dummy/tests/test_distance_aware_follow.py` | `apps/dummy/experiments/deployment_20260915/tests/test_distance_aware_follow.py` | 隔离旧实现；正式入口保持新版 |
| A | `apps/dummy/tests/test_dume_touch_r1_follow_control.py` | `apps/dummy/experiments/deployment_20260915/tests/test_dume_touch_r1_follow_control.py` | 隔离旧实现；正式入口保持新版 |
| A | `apps/dummy/tests/test_follow3d_depth_estimator.py` | `apps/dummy/experiments/deployment_20260915/tests/test_follow3d_depth_estimator.py` | 隔离旧实现；正式入口保持新版 |
| A | `apps/dummy/tests/test_follow3d_diagnostics.py` | `apps/dummy/experiments/deployment_20260915/tests/test_follow3d_diagnostics.py` | 隔离旧实现；正式入口保持新版 |
| A | `apps/dummy/tests/test_follow3d_handeye_projector.py` | `apps/dummy/experiments/deployment_20260915/tests/test_follow3d_handeye_projector.py` | 隔离旧实现；正式入口保持新版 |
| A | `apps/dummy/tests/test_follow3d_modularity.py` | `apps/dummy/experiments/deployment_20260915/tests/test_follow3d_modularity.py` | 隔离旧实现；正式入口保持新版 |
| A | `apps/dummy/tests/test_follow_loop_state.py` | `apps/dummy/experiments/deployment_20260915/tests/test_follow_loop_state.py` | 隔离旧实现；正式入口保持新版 |
| A | `apps/dummy/tests/test_head_body_controller.py` | `apps/dummy/experiments/deployment_20260915/tests/test_head_body_controller.py` | 隔离旧实现；正式入口保持新版 |
| A | `apps/dummy/tests/test_head_body_visualizer.py` | `apps/dummy/experiments/deployment_20260915/tests/test_head_body_visualizer.py` | 隔离旧实现；正式入口保持新版 |
| M | `apps/dummy/tests/test_offline.py` | `apps/dummy/experiments/deployment_20260915/tests/test_offline.py` | 隔离旧实现；正式入口保持新版 |
| A | `apps/dummy/tests/test_person_lock_tracker.py` | `apps/dummy/experiments/deployment_20260915/tests/test_person_lock_tracker.py` | 隔离旧实现；正式入口保持新版 |
| A | `apps/dummy/tests/test_rgbd_target.py` | `apps/dummy/experiments/deployment_20260915/tests/test_rgbd_target.py` | 隔离旧实现；正式入口保持新版 |
| A | `apps/dummy/tests/test_robot_ws_client.py` | `apps/dummy/experiments/deployment_20260915/tests/test_robot_ws_client.py` | 隔离旧实现；正式入口保持新版 |
| A | `apps/dummy/tests/test_virtual_3d_target_projector.py` | `apps/dummy/experiments/deployment_20260915/tests/test_virtual_3d_target_projector.py` | 隔离旧实现；正式入口保持新版 |
| A | `apps/dummy/tests/test_workspace_guard.py` | `apps/dummy/experiments/deployment_20260915/tests/test_workspace_guard.py` | 隔离旧实现；正式入口保持新版 |
| A | `apps/dummy/tests/test_yolo_person_detector.py` | `apps/dummy/experiments/deployment_20260915/tests/test_yolo_person_detector.py` | 隔离旧实现；正式入口保持新版 |
| M | `apps/launcher/src/cli.js` | `apps/launcher/src/cli.js` | 保留或按接口冲突适配 |
| A | `apps/launcher/src/meituan-vision-repair.js` | `apps/launcher/src/meituan-vision-repair.js` | 保留或按接口冲突适配 |
| A | `apps/launcher/src/one-click.js` | `apps/launcher/src/one-click.js` | 保留或按接口冲突适配 |
| M | `apps/web/public/css/style.css` | `apps/web/public/css/style.css` | 保留或按接口冲突适配 |
| M | `apps/web/public/index.html` | `apps/web/public/index.html` | 保留或按接口冲突适配 |
| M | `apps/web/public/js/main.js` | `apps/web/public/js/main.js` | 保留或按接口冲突适配 |
| M | `apps/web/public/js/voice-control.js` | `apps/web/public/js/voice-control.js` | 保留或按接口冲突适配 |
| M | `apps/web/src/config.js` | `apps/web/src/config.js` | 保留或按接口冲突适配 |
| A | `apps/web/src/language/camera-x-step.js` | `apps/web/src/language/camera-x-step.js` | 保留或按接口冲突适配 |
| M | `apps/web/src/language/directional-joint-control.js` | `apps/web/src/language/directional-joint-control.js` | 保留或按接口冲突适配 |
| M | `apps/web/src/language/language-upstream-bridge.js` | `apps/web/src/language/language-upstream-bridge.js` | 保留或按接口冲突适配 |
| M | `apps/web/src/language/manual-joint-control.js` | `apps/web/src/language/manual-joint-control.js` | 保留或按接口冲突适配 |
| M | `apps/web/src/robot-proxy.js` | `apps/web/src/robot-proxy.js` | 保留或按接口冲突适配 |
| M | `apps/web/src/server.js` | `apps/web/src/server.js` | 保留或按接口冲突适配 |
| M | `apps/web/src/websocket-proxy.js` | `apps/web/src/websocket-proxy.js` | 保留或按接口冲突适配 |
| M | `configs/README.md` | `configs/README.md` | 合并/更新说明 |
| M | `configs/runtime/manual-control.json` | `configs/runtime/manual-control.json` | 保留或按接口冲突适配 |
| A | `docs/services/BOTTLE_PREVIEW.md` | `docs/services/BOTTLE_PREVIEW.md` | 合并/更新说明 |
| A | `fixed_tcp_demo.py` | `apps/fixed_tcp_demo/fixed_tcp_demo.py` | 迁移演示并适配路径 |
| A | `fixed_tcp_demo/README.md` | `apps/fixed_tcp_demo/README.md` | 迁移演示并适配路径 |
| A | `fixed_tcp_demo/arm.py` | `History/fixed-tcp-before-port3000/arm.py` | 新版改用 3000；保留旧入口用于追溯，不加载 |
| A | `fixed_tcp_demo/demo.py` | `apps/fixed_tcp_demo/demo.py` | 迁移演示并适配路径 |
| A | `fixed_tcp_demo/fixed_tcp_demo.py` | `apps/fixed_tcp_demo/fixed_tcp_demo.py` | 迁移演示并适配路径 |
| A | `fixed_tcp_demo/logger.py` | `apps/fixed_tcp_demo/logger.py` | 迁移演示并适配路径 |
| A | `fixed_tcp_demo/safety.py` | `apps/fixed_tcp_demo/safety.py` | 迁移演示并适配路径 |
| A | `fixed_tcp_demo/trajectory.py` | `apps/fixed_tcp_demo/trajectory.py` | 迁移演示并适配路径 |
| M | `platform/contracts/schemas/execution-primitive.schema.json` | `platform/contracts/schemas/execution-primitive.schema.json` | 保留或按接口冲突适配 |
| M | `services/README.md` | `services/README.md` | 合并/更新说明 |
| A | `services/robot/config/formal-pregrasp-speed.patch` | `services/robot/config/formal-pregrasp-speed.patch` | 保留或按接口冲突适配 |
| A | `services/robot/config/sdk-joint-speed.patch` | `services/robot/config/sdk-joint-speed.patch` | 保留或按接口冲突适配 |
| A | `services/robot/src/joint_speed_policy.py` | `services/robot/src/joint_speed_policy.py` | 保留或按接口冲突适配 |
| M | `services/robot/src/robot-controller.js` | `services/robot/src/robot-controller.js` | 保留或按接口冲突适配 |
| M | `services/robot/src/startouch-bridge.js` | `services/robot/src/startouch-bridge.js` | 保留或按接口冲突适配 |
| M | `services/robot/src/startouch_bridge.py` | `services/robot/src/startouch_bridge.py` | 保留或按接口冲突适配 |
| M | `services/speech/README.md` | `services/speech/README.md` | 合并/更新说明 |
| M | `services/speech/src/voice_agent.py` | `services/speech/src/voice_agent.py` | 保留或按接口冲突适配 |
| M | `services/speech/src/voice_bridge.py` | `services/speech/src/voice_bridge.py` | 保留或按接口冲突适配 |
| M | `services/vision/python/camera_bridge.py` | `services/vision/python/camera_bridge.py` | 保留或按接口冲突适配 |
| A | `services/vision/python/handeye_projection.py` | `services/vision/python/handeye_projection.py` | 保留或按接口冲突适配 |
| M | `services/vision/src/camera-process.js` | `services/vision/src/camera-process.js` | 保留或按接口冲突适配 |
| M | `services/vision/src/config.js` | `services/vision/src/config.js` | 保留或按接口冲突适配 |
| A | `services/vision/src/meituan-raw-view.js` | `services/vision/src/meituan-raw-view.js` | 保留或按接口冲突适配 |
| M | `services/vision/src/server.js` | `services/vision/src/server.js` | 保留或按接口冲突适配 |
| M | `skills/README.md` | `skills/README.md` | 合并/更新说明 |
| A | `skills/manipulation/bottlegrasp/apps/bottle_pick/kinematic_preview.js` | `skills/manipulation/bottlegrasp/apps/bottle_pick/kinematic_preview.js` | 保留或按接口冲突适配 |
| A | `skills/manipulation/bottlegrasp/apps/bottle_pick/preview_ik.py` | `skills/manipulation/bottlegrasp/apps/bottle_pick/preview_ik.py` | 保留或按接口冲突适配 |
| A | `skills/manipulation/bottlegrasp/apps/bottle_pick/test_kinematic_preview.py` | `skills/manipulation/bottlegrasp/apps/bottle_pick/test_kinematic_preview.py` | 保留或按接口冲突适配 |
| M | `skills/manipulation/bottlegrasp/apps/bottle_pick/web_server.js` | `skills/manipulation/bottlegrasp/apps/bottle_pick/web_server.js` | 保留或按接口冲突适配 |
| M | `skills/manipulation/bottlegrasp/configs/action.yaml` | `skills/manipulation/bottlegrasp/configs/action.yaml` | 保留或按接口冲突适配 |
| A | `skills/manipulation/bottlegrasp/configs/action/evidence/urdf-grip-transform-candidate-20261002.json` | `skills/manipulation/bottlegrasp/configs/action/evidence/urdf-grip-transform-candidate-20261002.json` | 保留或按接口冲突适配 |
| A | `skills/manipulation/bottlegrasp/docs/action/grip-live-demo.md` | `skills/manipulation/bottlegrasp/docs/action/grip-live-demo.md` | 合并/更新说明 |
| A | `skills/manipulation/bottlegrasp/docs/action/supervised-test-grasp.md` | `skills/manipulation/bottlegrasp/docs/action/supervised-test-grasp.md` | 合并/更新说明 |
| A | `skills/manipulation/bottlegrasp/scripts/action/grip_live_demo.js` | `skills/manipulation/bottlegrasp/scripts/action/grip_live_demo.js` | 保留或按接口冲突适配 |
| A | `skills/manipulation/bottlegrasp/scripts/action/supervised_test_grasp.js` | `skills/manipulation/bottlegrasp/scripts/action/supervised_test_grasp.js` | 保留或按接口冲突适配 |
| M | `skills/manipulation/bottlegrasp/src/thirdhand_va/action/adapters/robot_ws_client.js` | `skills/manipulation/bottlegrasp/src/thirdhand_va/action/adapters/robot_ws_client.js` | 保留或按接口冲突适配 |
| M | `skills/manipulation/bottlegrasp/src/thirdhand_va/action/adapters/vision_client.js` | `skills/manipulation/bottlegrasp/src/thirdhand_va/action/adapters/vision_client.js` | 保留或按接口冲突适配 |
| M | `skills/manipulation/bottlegrasp/src/thirdhand_va/action/adapters/vision_service_client.js` | `skills/manipulation/bottlegrasp/src/thirdhand_va/action/adapters/vision_service_client.js` | 保留或按接口冲突适配 |
| M | `skills/manipulation/bottlegrasp/src/thirdhand_va/action/config.js` | `skills/manipulation/bottlegrasp/src/thirdhand_va/action/config.js` | 保留或按接口冲突适配 |
| M | `skills/manipulation/bottlegrasp/src/thirdhand_va/action/grasp/grasp_controller.js` | `skills/manipulation/bottlegrasp/src/thirdhand_va/action/grasp/grasp_controller.js` | 保留或按接口冲突适配 |
| A | `skills/manipulation/bottlegrasp/src/thirdhand_va/action/grasp/grip_transform.js` | `skills/manipulation/bottlegrasp/src/thirdhand_va/action/grasp/grip_transform.js` | 保留或按接口冲突适配 |
| A | `skills/manipulation/bottlegrasp/src/thirdhand_va/action/grasp/lift_only_plan.js` | `skills/manipulation/bottlegrasp/src/thirdhand_va/action/grasp/lift_only_plan.js` | 保留或按接口冲突适配 |
| A | `skills/manipulation/bottlegrasp/src/thirdhand_va/action/operator/supervised_preview.js` | `skills/manipulation/bottlegrasp/src/thirdhand_va/action/operator/supervised_preview.js` | 保留或按接口冲突适配 |
| A | `skills/manipulation/bottlegrasp/src/thirdhand_va/action/operator/supervised_test_session.js` | `skills/manipulation/bottlegrasp/src/thirdhand_va/action/operator/supervised_test_session.js` | 保留或按接口冲突适配 |
| M | `skills/manipulation/bottlegrasp/tests/action/adapters/clients.test.js` | `skills/manipulation/bottlegrasp/tests/action/adapters/clients.test.js` | 保留或按接口冲突适配 |
| M | `skills/manipulation/bottlegrasp/tests/action/adapters/robot_ws_client.test.js` | `skills/manipulation/bottlegrasp/tests/action/adapters/robot_ws_client.test.js` | 保留或按接口冲突适配 |
| M | `skills/manipulation/bottlegrasp/tests/action/adapters/vision_service_client.test.js` | `skills/manipulation/bottlegrasp/tests/action/adapters/vision_service_client.test.js` | 保留或按接口冲突适配 |
| M | `skills/manipulation/bottlegrasp/tests/action/config.test.js` | `skills/manipulation/bottlegrasp/tests/action/config.test.js` | 保留或按接口冲突适配 |
| M | `skills/manipulation/bottlegrasp/tests/action/grasp/grasp_controller.test.js` | `skills/manipulation/bottlegrasp/tests/action/grasp/grasp_controller.test.js` | 保留或按接口冲突适配 |
| A | `skills/manipulation/bottlegrasp/tests/action/grasp/grip_transform.test.js` | `skills/manipulation/bottlegrasp/tests/action/grasp/grip_transform.test.js` | 保留或按接口冲突适配 |
| A | `skills/manipulation/bottlegrasp/tests/action/grasp/lift_only_plan.test.js` | `skills/manipulation/bottlegrasp/tests/action/grasp/lift_only_plan.test.js` | 保留或按接口冲突适配 |
| A | `skills/manipulation/bottlegrasp/tests/action/grip_live_demo.test.js` | `skills/manipulation/bottlegrasp/tests/action/grip_live_demo.test.js` | 保留或按接口冲突适配 |
| A | `skills/manipulation/bottlegrasp/tests/action/operator/supervised_preview.test.js` | `skills/manipulation/bottlegrasp/tests/action/operator/supervised_preview.test.js` | 保留或按接口冲突适配 |
| A | `skills/manipulation/bottlegrasp/tests/action/operator/supervised_test_grasp.test.js` | `skills/manipulation/bottlegrasp/tests/action/operator/supervised_test_grasp.test.js` | 保留或按接口冲突适配 |
| A | `skills/manipulation/bottlegrasp/tests/action/operator/supervised_test_session.test.js` | `skills/manipulation/bottlegrasp/tests/action/operator/supervised_test_session.test.js` | 保留或按接口冲突适配 |
| A | `skills/manipulation/bottlegrasp/tests/action/operator/web_server.test.js` | `skills/manipulation/bottlegrasp/tests/action/operator/web_server.test.js` | 保留或按接口冲突适配 |
| M | `skills/manipulation/bottlegrasp/tests/fixtures/action/handeye-clearance.json` | `skills/manipulation/bottlegrasp/tests/fixtures/action/handeye-clearance.json` | 保留或按接口冲突适配 |
| M | `tests/node/contracts/contracts.test.js` | `tests/node/contracts/contracts.test.js` | 保留或按接口冲突适配 |
| A | `tests/node/launcher/one-click.test.js` | `tests/node/launcher/one-click.test.js` | 保留或按接口冲突适配 |
| M | `tests/node/robot_service/config.test.js` | `tests/node/robot_service/config.test.js` | 保留或按接口冲突适配 |
| M | `tests/node/robot_service/execution-gateway.test.js` | `tests/node/robot_service/execution-gateway.test.js` | 保留或按接口冲突适配 |
| M | `tests/node/vision_service/camera-process.test.js` | `tests/node/vision_service/camera-process.test.js` | 保留或按接口冲突适配 |
| M | `tests/node/vision_service/server.test.js` | `tests/node/vision_service/server.test.js` | 保留或按接口冲突适配 |
| A | `tests/python/fixed_tcp_demo/test_fixed_tcp_demo.py` | `tests/python/fixed_tcp_demo/test_fixed_tcp_demo.py` | 保留或按接口冲突适配 |
| M | `tests/python/vision_service/test_camera_fallback.py` | `tests/python/vision_service/test_camera_fallback.py` | 保留或按接口冲突适配 |
| A | `tests/python/vision_service/test_handeye_projection.py` | `tests/python/vision_service/test_handeye_projection.py` | 保留或按接口冲突适配 |
| A | `tests/python/vision_service/test_runtime_confidence.py` | `tests/pending/vision/test_runtime_confidence.py` | 未实现接口契约，保留待办 |
| A | `tools/launcher/README.md` | `tools/launcher/README.md` | 合并/更新说明 |
| M | `tools/launcher/ubuntu/start-thirdhand.sh` | `tools/launcher/ubuntu/start-thirdhand.sh` | 保留或按接口冲突适配 |
| M | `tools/launcher/windows/install-thirdhand-shortcut.ps1` | `tools/launcher/windows/install-thirdhand-shortcut.ps1` | 保留或按接口冲突适配 |
