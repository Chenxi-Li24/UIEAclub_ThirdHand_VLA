# ROS2 Wrapper for Devices

## Installation Instructions

The following instructions were verified with ROS2 Galactic on **Ubutnu 20.04**.

### Dependencies
#### Install ROS2 packages [ros-galactic-desktop](http://docs.ros.org/en/galactic/Installation/Ubuntu-Install-Debians.html)

### 更新Ubuntu发行版，包括获取最新的稳定内核:

sudo apt-get update && sudo apt-get upgrade && sudo apt-get dist-upgrade

#### Ubuntu环境安装
#### 安装依赖库：

sudo apt-get update
sudo apt-get install -y tree g++ cmake cmake-curses-gui pkg-config autoconf libtool libudev-dev libjpeg-dev zlib1g-dev libopencv-dev rapidjson-dev libeigen3-dev libboost-thread-dev libboost-filesystem-dev libboost-system-dev libboost-program-options-dev libboost-date-time-dev liboctomap-dev

### 安装usb权限
#### 下载 权限文件 99-xvisio.rules,在下载文件的目录下打开终端，输入命令：

sudo cp 99-xvisio.rules /etc/udev/rules.d/
sudo udevadm control --reload-rules && udevadm trigger

### 安装xvsdk
#### 安装最新版本xvsdk

sudo dpkg -i XVSDK_focal_amd64_0930.deb

#### 如遇安装失败，缺少相关三方包，可以运行 sudo apt install --fix-broken 来补全。

### Install xv_ROS2_wrapper source
```bash

mkdir -p ~/ros2_ws/src
sudo cp -r /usr/share/ros2-wrapper/xv_ros2_msgs ~/ros2_ws/src
sudo cp -r /usr/share/ros2-wrapper/xv_sdk_ros2 ~/ros2_ws/src

#build
cd ~/ros2_ws
colcon build  --packages-select xv_ros2_msgs
colcon build  --packages-select xv_sdk_ros2 --cmake-args -DXVSDK_INCLUDE_DIRS="/usr/include/xvsdk" -DXVSDK_LIBRARIES="/usr/lib/libxvsdk.so"
```
**Note:**
Please install SDK before building.

## Usage Instructions

### Start the node
To start the node in ROS2, plug in the device, then type the following command:

```bash
source /opt/ros/galactic/setup.bash
cd ~/ros2_ws
. install/setup.bash
# To launch with "ros2 run"
ros2 launch xv_sdk_ros2 xv_sdk_node_launch.py
```

You can use the `ros2 topic list` command to view the topics provided by the node, use `ros2 service list` to view the services provided by the node.

### 扩展usb带宽（用于多设备）

#### 新建command窗口，运行以下命令打开配置文件：
sudo vi /etc/default/grub

#### 将以下行内容：
    GRUB_CMDLINE_LINUX_DEFAULT="quiet splash"
#### 修改为：
    GRUB_CMDLINE_LINUX_DEFAULT="quiet splash usbcore.usbfs_memory_mb=128"

#### 更新GRUB：
    sudo update-grub

#### 重启电脑，使用以下命令查看是否生效：
    cat /sys/module/usbcore/parameters/usbfs_memory_mb

### 使用service去切换显示畸变图像(SN需根据当前设备sn输入，通过ros2 service list命令可以查看具体sn值)
```bash
ros2 service call  /xv_sdk/SN/rgb/flag std_srvs/srv/SetBool "{data: true}"  #显示畸变图像
ros2 service call  /xv_sdk/SN/rgb/flag std_srvs/srv/SetBool "{data: false}" #显示原始图像
```

### 扩展usb带宽（用于多设备）

#### 新建command窗口，运行以下命令打开配置文件：
sudo vi /etc/default/grub

#### 将以下行内容：
    GRUB_CMDLINE_LINUX_DEFAULT="quiet splash"
#### 修改为：
    GRUB_CMDLINE_LINUX_DEFAULT="quiet splash usbcore.usbfs_memory_mb=128"

#### 更新GRUB：
    sudo update-grub

#### 重启电脑，使用以下命令查看是否生效：
    cat /sys/module/usbcore/parameters/usbfs_memory_mb

## 在rviz中显示点云
1. 打开rviz
2. 修改Displays->Global Options->Fixed Frame下拉框选择**xv_sdk/map_optical_frame**
3. 点击Add按钮->By topic->```<device_name>```->```/rgbPointCloud``` -> PointCloud2

### tip
- PointCloud2->Status:OK即为显示点云正常
- PointCloud2->Size(m)为设置每一个点的大小，(Grid->Cell Size默认为1，可以相对于Grid->Cell Size设置点云点的大小)

### 使用service开启/关闭外部夹具数据输出(SN需根据当前设备sn输入，通过ros2 service list命令可以查看具体sn值)
```bash
ros2 service call /xv_sdk/SN/start_clamp std_srvs/srv/Trigger #开启夹具数据输出
ros2 service call /xv_sdk/SN/stop_clamp std_srvs/srv/Trigger #关闭夹具数据输出
```

    

