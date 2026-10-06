# ROS1 Wrapper for  Devices
## Installation Instructions

The following instructions were verified with ROS1 noetic on **Ubutnu 20.04**.

### 设置你的sources.list
sudo rm /etc/apt/sources.list.dros-latest.list
### 若提示无该文件可删除，跳过继续进行下一步
sudo sh -c 'echo "deb http://packages.ros.org/ros/ubuntu $(lsb_release -sc) main" > /etc/apt/sources.list.d/ros-latest.list'

### 设置密钥
sudo apt-key adv --keyserver 'hkp://keyserver.ubuntu.com:80' --recv-key C1CF6E31E6BADE8868B172B4F42ED6FBAB17C654

### 安装ROS系统
#### 更新系统软件包
sudo apt update

#### 安装ROS系统
sudo apt -y install ros-noetic-desktop-full ros-noetic-ddynamic-reconfigure

#### 相关依赖安装
 sudo apt install -y python3-rosdep python3-rosinstall python3-rosinstall-generator python3-wstool build-essential

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

### 环境配置
Ubuntu20.04
Bash
echo "source /opt/ros/noetic/setup.bash" >> ~/.bashrc
source ~/.bashrc

### 初始化rosdep
sudo rosdep init
rosdep update

### ROS wrapper 代码编译
#### 初始化工作空间
##### 创建目录
mkdir -p ~/catkin_ws/src

##### 进入工作空间
cd ~/catkin_ws/

##### 工作空间环境初始化
catkin_make
source ${HOME}/catkin_ws/devel/setup.bash
echo "source ${HOME}/catkin_ws/devel/setup.bash" >> ~/.bashrc

#### xv_sdk编译
##### 在Ubuntu xvisio SDK安装目录下打开终端(默认安装目录/usr/share/ros-wrapper)
##### 拷贝xv_sdk到工作空间
cp -r /usr/share/ros-wrapper/xv_sdk ~/catkin_ws/src/

##### 安装工作空间中ROS包的依赖
rosdep install --from-paths src --ignore-src -r -y

##### 编译
cd ~/catkin_ws/
catkin_make -DXVSDK_INCLUDE_DIRS="/usr/include/xvsdk" -DXVSDK_LIBRARIES="/usr/lib/libxvsdk.so" 

##### xv_sdk 节点启动
roslaunch xv_sdk xv_sdk.launch

### 使用service开启/关闭外部夹具数据输出(SN需根据当前设备sn输入，通过rosservice list命令可以查看具体sn值)
```bash
rosservice call /xv_sdk/SN/clamp/start #开启夹具数据输出
rosservice call /xv_sdk/SN/clamp/stop #关闭夹具数据输出
```
