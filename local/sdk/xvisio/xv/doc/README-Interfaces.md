# Intefaces for Devices

## 更新Ubuntu发行版，包括获取最新的稳定内核:

sudo apt-get update && sudo apt-get upgrade && sudo apt-get dist-upgrade

### Ubuntu环境安装
### 安装依赖库：

sudo apt-get update
sudo apt-get install -y tree g++ cmake cmake-curses-gui pkg-config autoconf libtool libudev-dev libjpeg-dev zlib1g-dev libopencv-dev rapidjson-dev libeigen3-dev libboost-thread-dev libboost-filesystem-dev libboost-system-dev libboost-program-options-dev libboost-date-time-dev liboctomap-dev

## 安装usb权限
### 下载 权限文件 99-xvisio.rules,在下载文件的目录下打开终端，输入命令：

sudo cp 99-xvisio.rules /etc/udev/rules.d/
sudo udevadm control --reload-rules && udevadm trigger

## 安装xvsdk
### 安装最新版本xvsdk

sudo dpkg -i XVSDK_focal_amd64_0930.deb

### 如遇安装失败，缺少相关三方包，可以运行 sudo apt install --fix-broken 来补全。

## C接口头文件介绍
目前针对python及C接口，将xvsdk c++接口封装为c风格接口，对应两个头文件CInterfaceGenral.h及CInterfaces.h，存放在/usr/include/xvsdk/中，其中CInterfaces.h对应python接口，CInterfaceGenral.h对应c接口。并提供两个示例代码用于参考接口调用。

## Python示例介绍
XVSDK安装完毕后，python示例安装在/usr/share/python-wrapper目录中，其中xvsdk.py包含python封装的xvsdk相关接口及数据定义，PythonDemo.py包含Python接口的调用示例和数据解析示例

### Linux/Ubuntu Python环境安装

#### Python环境搭建

安装python环境，建议使用python3.9。安装命令如下：
sudo apt update
sudo apt install software-properties-common
sudo add-apt-repository ppa:deadsnakes/ppa
sudo apt install python3.9
sudo apt install -y python3-pip
sudo pip install keyboard

启动终端并导航到 Python wrapper 安装路径 "/usr/share/python-wrapper"，或者将整个python-wrapper目录拷贝出来
cd /usr/share/python-wrapper
运行PythonDemo.py文件
python3 PythonDemo.py

## C接口示例介绍
XVSDK安装完毕后，C接口示例安装在/usr/share/xvsdk/multi-devices-c-interface中。

### 代码编译运行
拷贝/usr/share/xvsdk/multi-devices-c-interface目录到测试目录中，执行以下步骤。

mkdir build
cd build
cmake ..
make

编译完成后，build目录会生成multi-devices-c-interface工具，./multi-devices-c-interface 运行即可查看数据流


    

