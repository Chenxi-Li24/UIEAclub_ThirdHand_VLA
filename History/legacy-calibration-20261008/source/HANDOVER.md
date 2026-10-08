# 瓶子抓取项目交接文档

## 当前状态

**文件**: `/home/nieqingcao/calibration/bottle_grasp_server.py`  
**端口**: `http://192.168.58.68:8088`  
**Git**: commit `9d39ec0` 及之后的改动在 master 分支

## 操作流程

1. 打开 `http://192.168.58.68:8088`
2. 点 **Connect Arm** → 自动 `go_home()` + 打开夹爪
3. 放瓶子在桌面 → 点 **Grasp #N**
4. 可选：点 **Lock #N** 锁定追踪某个瓶子
5. 可选：点 **Calibrate Desk**（放 Charuco 板）+ **Load Desk Ref**（加载上次标定）

## 硬件

- 机械臂：Startouch FastTouchV3，CAN 接口 can0
- 相机：Lumos Touch R1 板载相机，USB 040e:f408，V4L2 /dev/video1
- SEUCM 超广角 220° 1280×1280（fx=392.168, alpha=0.679, beta=0.749）
- YOLOv8n 检测瓶子（class 39），CPU 推理 ~500ms

## 当前方案：像素偏移相对移动（工作中）

**原理**: 瓶子在画面中偏离中心多少像素 → 臂从当前位置相对移动多少。不依赖绝对坐标。

**映射**（经物理测试确认，2026-07-31 修正）:
```python
SCALE_X = 0.0012   # 画面下(dv>0,近) → 基座后(-X);  画面上(dv<0,远) → 基座前(+X)
SCALE_Y = 0.0008   # 画面右(du>0) → 基座左(+Y);     画面左(du<0) → 基座右(-Y)
dx = -dv * SCALE_X （clamp ±25cm）
dy =  du * SCALE_Y （clamp ±25cm）
```

**运动**: hover(抬升8cm→平移XY) → descend(直降5cm) → 夹取 → 回家 → 开爪

**优点**: 简单，不依赖标定，近距离准确
**缺点**: 固定SCALE无法同时适配远近；clamp 限制远距离

## 已尝试方案

| 方案 | 结果 | 问题 |
|------|------|------|
| **Charuco桌面标定 + SEUCM射线求交** | 方向对，差固定偏移 | 针孔PnP在鱼眼上解T_base_board有旋转误差 |
| **SEUCM PnP迭代优化** | 不稳定 | scipy least_squares 解不稳定，dt值跳变 |
| **SEUCM射线 + Z_DESK平面求交（无手眼）** | 偏移极小 | T_flange_camera Z方向误差大(cam_z=-0.05) |
| **自适应SCALE（随dv变化）** | 近瓶过头/远瓶不够 | 线性公式无法拟合鱼眼非线性 |
| **EE坐标系偏差** | 旋转未对齐 | 需要重做手眼标定 |
| **夹爪开度检测** | 工作中 | gripper_position>0.25=夹到, <0.25=空夹 |
| **颜色直方图追踪** | 工作中 | IoU+颜色匹配，锁定瓶子不跳ID |

## 待解决问题

1. **远近适配**: 固定SCALE对大dv(近瓶)偏大、小dv(远瓶)偏小。需要非线性映射
2. **手眼标定**: T_flange_camera 用针孔PnP标定，SEUCM图像有系统误差，需用SEUCM投影重标
3. **网页偶尔卡死**: Flask单线程 + YOLO推理。建议用生产级WSGI服务器
4. **夹取高度**: hover后descend 5cm可能碰倒瓶子，需根据实际调节

## 关键参数

```python
# /home/nieqingcao/calibration/bottle_grasp_server.py

# 相机
FX, FY = 392.168, 392.168
U0, V0 = 637.761, 640.597
ALPHA, BETA = 0.678979, 0.749026

# 手眼标定
T_flange_camera = [[0.9895, 0.1436, -0.0146, 0.1732],
                   [-0.1374, 0.9684, 0.2084, -0.1575],
                   [0.0441, -0.2042, 0.9779, -0.2286],
                   [0, 0, 0, 1]]

# 移动（用户可自行修改）
SCALE_X = 0.0012  # 前后缩放
SCALE_Y = 0.0008  # 水平缩放
clamp = ±0.25      # 最大移动量

# 夹爪
GRIPPER_OPEN = 1.0
GRIPPER_CLOSE = 0.15
```

## Charuco 标定板

- 9×12，方格15mm，marker 11.25mm，DICT_5X5_100
- 用于手眼标定（handeye_calib.py :8089）和桌面标定（/calibrate_desk）
- 桌面标定结果保存在 desk_ref.json
