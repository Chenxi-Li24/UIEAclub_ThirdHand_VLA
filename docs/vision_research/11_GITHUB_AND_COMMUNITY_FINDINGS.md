# GitHub 与社区发现

社区证据用于发现工程陷阱，不作为安全或数学结论的唯一依据。核心决策仍以论文、官方文档、源码和本机测量为准。

## GitHub/官方仓库

- FastUMI_Camera 官方 README 明确：1280×1280 YU12/I420、100 fps 目标、buffer size 1、厂商内参文件为 SEUCM。仓库没有根 LICENSE。
- Kalibr 支持 EUCM 与 Double Sphere，并建议 AprilGrid，因为部分可见仍可检测且不易发生姿态翻转。
- RealSense 官方投影文档区分 deprojection、pointcloud、map_to 和 align；对齐后必须使用目标流对应的内参。
- RealSense 官方多相机说明指出：无硬件同步时设备异步；低队列容量可限制陈旧帧，但不能让不同相机真正同步。
- Ultralytics tracker 文档暴露 `track_high_thresh/low_thresh/new_track_thresh/track_buffer/match_thresh`；官方 issue 中存在检测有框但无 ID、相同 ID 误用和遮挡后换 ID 的报告，说明不能把 tracker id 当永久实体身份。
- OpenCV 官方 `calibrateHandEye` 明确输入/输出坐标方向；现有自定义函数与文档不一致。

## Reddit（低权重经验）

- 社区正确指出 RealSense depth 是 optical-axis Z，而不是 range；这与官方投影 API 和本机代码问题一致。
- 多个机器人/视觉帖子反复提到 D435 近距离、反光/透明和边缘深度不稳定，以及手眼标定方向/坐标约定是常见故障。
- 对 eye-in-hand 的实用建议常是 stop-settle-observe，再执行；这与本项目无硬同步且 D435 最小距离的限制相符。
- 对 AnyGrasp 的讨论普遍提到授权壁垒，支持不把它作为默认开源依赖。

## Bilibili/知乎（低权重经验）

- Bilibili 有 D435+YOLO+机械臂抓取和 D455 眼在手上/外标定演示，能作为操作流程参考，但未提供可审核的误差、失败率和许可证，不能当验收证据。
- 知乎“小鱼开源库”文章强调眼在手上/外标定需要同时获取末端 pose 与标定板 pose；该原则正确，但仍应按 OpenCV/论文坐标定义实现并独立验证。

## YouTube/演示视频

ViSP、Contact-GraspNet、FoundationPose 等官方项目提供视频。视频能确认功能形态和交互方式，不证明在 Lumos 220°、D435、RTX 5060 8GB 与 Startouch 机械臂上的精度和实时性。

## 对本项目的具体启示

1. 所有 tracker 参数和 ID 行为都必须通过遮挡/相机运动回放测试。
2. 相机坐标轴、depth 语义和变换方向必须成为类型/测试，不依赖注释或经验。
3. USB 断连/恢复不应由应用每次启动隐式写 sysfs；健康状态应被观测和报告。
4. 演示级“点一下抓取”代码不满足状态机安全要求；必须有命令关联、超时、失败终止和人工批准。
5. 所有社区推荐模型先过许可证、资源和本机 benchmark 三道门。
