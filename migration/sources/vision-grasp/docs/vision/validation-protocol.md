# VA 固定实验瓶视觉验收协议

本协议只验收视觉，不移动机械臂，不计算基坐标，也不调用语音模块。

## 前置条件

使用序列号 250801DR48FP25002738 的 XVisio RGB-D 鱼眼相机。由操作者确认固定实验可乐瓶，采集至少 20 个正面、侧面和小角度参考视角。原始 RGB-D/XYZ 序列保存在 Git 外，Git 只保存内容哈希清单和报告。

## 相机检查

运行 `scripts/vision/validate_camera_alignment.py`，`duration-s` 设为 1800，
输出 `artifacts/vision/validation/camera.json`。默认报告只证明序列号、进程稳定、
时间单调和三数组同网格。只有使用标定靶完成独立几何检查后，才允许加入
`target-check-passed`；不能仅凭数组尺寸宣称几何对齐。

## 数据集

正样本只包含固定实验可乐瓶，覆盖中央工作区多个位置和旋转。负样本至少分别包含百事瓶、矿泉水瓶、普通瓶和可乐罐。困难、遮挡或深度不足样本也必须保留。

## 通过门槛

- 固定瓶正样本召回率不低于 95%；
- 声明负样本错误授权数为 0；
- 静态场景相机坐标系抓取点最大重复偏差不超过 5 mm；
- 所有不安全样本必须给出阻断原因；
- 失败时保留报告并返回非零，禁止自动降低阈值。

使用 `scripts/vision/evaluate_fixed_bottle.py` 读取
`artifacts/vision/validation/manifest.json` 并输出 `report.json`。

报告位姿坐标系只能是 xvisio_color，且始终声明 robot_control_enabled=false。手眼标定、语音触发、基坐标变换和机械臂抓放属于后续集成验收。
