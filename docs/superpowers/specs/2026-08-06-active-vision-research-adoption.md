# 主动视觉论文成果采用与可视化规格

日期：2026-08-06

状态：已完成一手来源调研，按现有真实数据合同落地

## 1. 采用原则

可视化必须帮助判断“检测到了什么、是不是同一实物、D435 深度是否足够、当前为何能/不能继续”，
并且只显示算法实际计算出的数据。论文中的图用于选择表达方式，不复制论文图片，也不生成系统尚未
计算的伪热力图。

## 2. 一手来源与工程选择

| 来源 | 可复用知识 | 本项目采用 | 暂不采用及原因 |
|---|---|---|---|
| DINOv3 论文与 Meta 官方实现 | 稠密 patch 特征、余弦相似度图、PCA 特征可视化 | 显示当前描述子与已绑定身份原型的真实余弦相似度；保留独立诊断接口 | 暂不在线输出完整 PCA/patch 热力图：当前部署是 DINOv2-S/14，且在线合同只保留池化描述子；先避免增加每目标稠密图的显存、CPU 和传输开销 |
| REMIND 论文与作者官方实现 | 感知—关联—更新三段式；work/stable 双记忆；全局 Hungarian；歧义分级；身份生命周期 | 显示身份阶段、命中次数、work/stable 原型容量、关联代价/原因；继续使用全局匹配和显式 `AMBIGUOUS` | 邻域上下文和 part/background 三通道尚未在本仓库实现，界面不得假装可用 |
| RTMDet 论文与 MMDetection 官方实现 | 实时实例分割；标准框、掩码、类别、分数可视化 | Lumos 主画面增加半透明实例掩码、边框、类别、分数和 `identity_id` | 不显示 detector 内部多尺度特征，因其不参与操作者决策 |
| MoveIt Servo 官方文档 | 视觉伺服命令形式；碰撞、奇异位形、平滑和关节限位检查 | 转化为主动观察执行的安全检查清单；保留停—看—确认、低速、小步和反馈关联 | 当前 Startouch 控制栈不是 ROS/MoveIt，且无已验证 URDF/SRDF/PlanningScene/控制器映射，因此不直接集成 |

## 3. 本轮可视化

### 3.1 Lumos 实例与身份叠加层

- RTMDet 实例掩码使用稳定的半透明颜色填充，保留原图纹理；
- 框标签显示 `类别 + detector 分数 + identity_id`；
- 颜色只表达身份/可操作状态，不表达机器人安全批准；
- 描述子相似度、关联代价和歧义原因通过结构化状态提供，不把新身份的自相似度伪装成关联证据。

### 3.2 REMIND 身份记忆卡

每个新鲜目标显示：

- `TENTATIVE / CONFIRMED / AMBIGUOUS` 等真实生命周期；
- work bank 与 stable bank 的实际原型数量；
- 历史命中次数；
- 有匹配时显示 DINO 原型余弦相似度和融合关联代价；
- 新建身份、低质量关联、竞争歧义等原因原样显示为诊断字段。

### 3.3 D435 深度质量视图

- D435 调试画面标出配置中宽高各 60% 的中央质量区；
- 保留深度伪彩小窗，并显示无效深度为黑色；
- 主动观察面板显示目标有效深度点数、落在中央质量区的比例、稳定样本数和剩余精调次数；
- 中央区域是质量门限，不是“必须对齐一个像素”的机械运动目标。

### 3.4 主动观察阶段轨迹

页面显示状态机阶段、会话/提议关联、证据摘要、单步上限、逐步确认和阻断原因。进入
`GRASP_PREVIEW` 时只显示三维几何预览，不提供抓取执行按钮。

## 4. 模块边界

```text
RTMDet adapter ── detections/masks ──┐
DINO adapter ─── descriptors ────────┼─> IdentityMemory ─> diagnostic DTO
D435 fusion ──── depth quality ──────┘                         │
                                                              v
render_overlay (纯图像渲染)                VisionStatus sanitizer (有限字段)
                                                              │
                                                              v
                                                     camera-test.html
```

- 模型适配器不依赖网页；
- 身份记忆不负责绘图；
- overlay 只渲染不可变诊断数据，不执行规划；
- Node 只发布白名单后的有限字段；
- 页面只显示状态并发送 ID，不携带坐标、关节或安全布尔值。

## 5. 后续升级门槛

迁移到 DINOv3-S/16 或启用稠密 patch 相似度图前，必须先在同一 Lumos 回放集比较身份准确率、
歧义拒绝率、P95 时延和峰值显存，并核验代码、模型权重及分发许可证。只有实际指标优于当前
DINOv2-S/14 且满足 8 GiB 显存预算，才更换在线主模型。

## 6. 参考来源

- DINOv3 paper: https://arxiv.org/abs/2508.10104
- DINOv3 official repository: https://github.com/facebookresearch/dinov3
- REMIND paper: https://arxiv.org/abs/2607.09267
- REMIND project and official method notes: https://cvar-vision-dl.github.io/remind-reid-tracker/
- REMIND official repository: https://github.com/cvar-vision-dl/remind-reid-tracker
- RTMDet paper: https://arxiv.org/abs/2212.07784
- MMDetection visualization guide: https://mmdetection.readthedocs.io/en/latest/user_guides/visualization.html
- MoveIt Servo tutorial: https://moveit.picknik.ai/main/doc/examples/realtime_servo/realtime_servo_tutorial.html
