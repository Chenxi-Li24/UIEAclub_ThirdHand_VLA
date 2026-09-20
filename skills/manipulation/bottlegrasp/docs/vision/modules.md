# V（Vision）模块说明

V 的正式输入是 Lumos Ego STD/XVisio 同源注册 RGB-D，正式输出是
`thirdhand-va-detection-v3`。V 永远不发送机器人命令。

| 模块 | 职责 | 输入 -> 输出 | 独立入口与预期结果 |
|---|---|---|---|
| `camera` | 采集/录制不可变 RGB-D 帧 | XVisio stream -> `RgbdFrame` bundle | `replay_rgbd.py` 输出帧摘要；live 脚本必须有 `--allow-camera` |
| `perception` | 通用 bottle 文本检测与实例分割 | RGB -> 授权候选、mask、descriptor | `debug_perception.py` 输出候选、模型来源和 DINO/SAM 耗时 |
| `tracking` | 后端关联和用户稳定编号分层 | 连续候选 -> `stable_id 1..5` | `debug_tracking.py` 输出逐帧 ID；换序 fixture 中物理瓶 ID 不变 |
| `geometry` | 平面、深度统计和直立侧抓候选；沿真实 base `+X` 轴检查邻瓶通道 | 注册 XYZ + mask + `T_base_camera` -> `GraspPoseCamera` | `debug_geometry.py` 输出候选 JSON 和轮廓 JPEG |
| `selection` | 锁定 L 请求的稳定 ID | `target_id + tracks` -> 唯一目标/阻断原因 | `stable_selector.py` 对应单元测试 |
| `pipeline.py` | 统一证据、状态和运动 epoch | `RgbdFrame` -> `VisionDecision` | `debug_pipeline.py --target-id 2 ...` 输出最终 v3 核心字段 |
| `visualization` | 叠加编号、选中态、深度和原因 | frame + decision -> overlay | `debug_visualization.py` 输出 JPEG 和深度统计 |
| `adapters` | 严格序列化 JSON/MJPEG | decision -> v3 event/stream | `event_publisher.py` 对应 adapter 测试 |
| `preview` | 只读查看、帧同步和窗口 | MJPEG/回放 -> VS Code/Ubuntu 画面 | 见 `docs/vision/preview.md` |

## 直接运行

```bash
PY=$HOME/miniconda3/envs/thirdhand-groundedsam2/bin/python

$PY scripts/vision/debug_tracking.py \
  --fixture tests/fixtures/tracking/reorder.json

$PY scripts/vision/build_debug_fixture.py

$PY scripts/vision/debug_geometry.py \
  artifacts/vision/debug-fixture/frame_000000 \
  artifacts/vision/debug-fixture/masks.npz \
  --mask-key mask_2 \
  --output-json artifacts/vision/debug/geometry.json \
  --output-image artifacts/vision/debug/geometry.jpg

$PY scripts/vision/debug_pipeline.py --target-id 2 \
  --synthetic-masks artifacts/vision/debug-fixture/masks.npz \
  artifacts/vision/debug-fixture/frame_000000 \
  --repeat-last 6
```

`debug_perception.py` 会加载本机已配置模型，但不会下载模型；`debug_pipeline.py` 不传
`--synthetic-masks` 时也会使用真实模型，传入后则只绕过感知、独立调试追踪/几何/决策；
`debug_tracking.py` 不需要模型；`debug_geometry.py` 只需要 bundle 和 mask。
`--repeat-last` 只在内存中为最后一张录制图生成新的递增帧号，用来观察 Stable ID 和
4-of-5 稳定窗口，不修改原始 bundle。

## 推荐断点

- 感知：`perception/grounded_sam.py` 的 `infer`，检查文本框、SAM mask 和 descriptor。
- Stable ID：`tracking/stable_ids.py` 的 `update`，检查 reservation/confirmed/occluded。
- 几何：`geometry/pointcloud.py` 的平面拟合和 `geometry/grasp_candidates.py` 的 blocker。
- Pipeline：`pipeline.py` 的 `process`，检查 `motion_epoch`、`stable_hits` 和 evidence ID。
- 输出：`adapters/event_publisher.py` 的 `build_detection_event`。

常见判断：没有候选先看模型和 prompt；ID 变化看 descriptor/关联阈值；几何拒绝看深度有效率、
瓶轴与桌面法向夹角、宽度是否超过 72 mm、base `+X` 插入通道是否碰邻瓶；ready 后仍不可
执行则继续检查 A 的标定、运行产物快照和安全门。
