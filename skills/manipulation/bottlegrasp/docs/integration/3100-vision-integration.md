# 3100 视觉流接入

规范相机桥入口是 Python 模块：

```text
apps.bottle_pick.camera_bridge
```

它兼容 ThirdHand CameraBridge 管道：stdout 输出主摄像头 multipart MJPEG，fd3 输出
逐行 `detection_result` JSON，fd4 输出带帧号、单调时间、观测时间和 SHA-256 的算法
叠加 MJPEG。VA 不启动第二个 3100 网站，也不修改机械臂、CAN、夹爪或执行逻辑。

协议编码位于 `thirdhand_va.vision.adapters`，Node 子进程适配器位于
`src/thirdhand_va/action/adapters/camera_bridge.js`。适配器从仓库根目录执行：

```bash
python -m apps.bottle_pick.camera_bridge ...
```

部署配置应使用模块名 `apps.bottle_pick.camera_bridge`，不再引用旧脚本路径，也不绑定
某台机器的绝对路径。

离线回放不会打开相机：

```bash
python -m apps.bottle_pick.camera_bridge \
  --source replay --bundles SAVED_BUNDLE --selection-side left --ordinal 2
```

实时模式要求相机已从手眼标定流程释放，并由用户明确传入 `--allow-camera` 或设置
`THIRDHAND_VA_ALLOW_CAMERA=1`。当前交付状态始终保持
`robot_control_enabled=false`；硬件验收结果单独记录。
