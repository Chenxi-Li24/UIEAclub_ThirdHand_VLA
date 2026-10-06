# FastUMI硬件sdk

## 📁 目录结构

```
vive/                                 # Vive 定位系统相关内容
├── doc/                              # Vive 使用与配置文档
│   ├── FastUMI_Hardware_Startup_Procedure_en.docx  # FastUMI 启动流程（英文）
│   ├── FastUMI_Hardware_Startup_Procedure_zh.docx  # FastUMI 启动流程（中文）
│   └── vive使用教程.docx                             # Vive 基础使用教程


xv/                                   # FastUMI 核心 SDK（XV SDK & ROS 支持）
├── doc/                              # FastUMI 硬件 / 接口 / ROS 文档
│   ├── README-Interfaces.md          # 硬件接口与数据说明
│   ├── README-ros1.md                # ROS1 使用说明
│   ├── README-ros2.md                # ROS2 使用说明
│   ├── ros1-topic 介绍.docx          # ROS1 Topic 说明文档
│   └── ros2-topic 介绍.docx          # ROS2 Topic 说明文档
│
├── scripts/                          # SDK 安装与系统配置脚本
│   ├── 99-xvisio.rules               # udev 规则（设备权限配置）
│   ├── README-install.md             # SDK 安装说明
│   ├── install-ros1.sh               # 一键安装 SDK + ROS1 功能包
│   ├── install-ros2.sh               # 一键安装 SDK + ROS2 功能包
│   ├── install-python.sh             # Python 运行环境安装脚本
│   └── multi-support.sh              # USB 带宽扩展（多设备运行必需）
│
├── sdk/                              # FastUMI 硬件 SDK 安装包（按版本归档）
│   └── XXX/                          # SDK 版本号（以交付版本为准）
│       ├── XVSDK_focal_amd64_XXX.deb  # Ubuntu 20.04 / ROS1
│       └── XVSDK_jammy_amd64_XXX.deb  # Ubuntu 22.04 / ROS2   
```

### 文件说明

| 文件 | 功能 | 使用场景 |
|------|------|---------|

---

## 🚀 快速开始

### 前置条件

1. **ROS环境安装**
   ```bash
   #建议安装ROS1 neotic
   wget http://fishros.com/install -O fishros && . fishros
   ```
---

## 📖 使用指南（单/双设备通用）

1. **安装SDK**
   ```bash
   cd xv/scripts/
   #ros1版本(recommended)
   sudo -E bash install-ros1.sh ../sdk/XXX/XVSDK_focal_amd64_XXX.deb
   ```
   
   ```bash
   cd xv/scripts/
   #ros2版本
   sudo -E bash install-ros2.sh ../sdk/XXX/XVSDK_jammy_amd64_XXX.deb
   ```

2. **连接FastUMI**
   ```bash
   cd ~/catkin_ws/
   roslaunch xv_sdk xv_sdk.launch

   ```
   
3. **扩展USB带宽(可选，多设备时必须先执行)**
   ```bash
   #执行完后会自动重启终端
   sudo -E bash multi-support.sh
   ```
   
3. **检查FastUMI状态**
可通过[FastUMI Monitor Tool](https://github.com/lumos-open/FastUMI_Monitor_Tool)对设备采集数据进行采样分析，查看设备运行状态是否正常。
---



## 🔍 故障排查

### 问题：SDK roslaunch启动失败

**检查：**
删除相关进程，重新启动SDK。




