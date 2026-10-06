#!/bin/bash

chmod 777 *

echo "install environment"
apt-get update
apt-get install -y tree g++ cmake cmake-curses-gui pkg-config autoconf libtool libudev-dev libjpeg-dev zlib1g-dev libopencv-dev rapidjson-dev libeigen3-dev libboost-thread-dev libboost-filesystem-dev libboost-system-dev libboost-program-options-dev libboost-date-time-dev liboctomap-dev doxygen libcxsparse3 libsuitesparse-dev
apt-get install --fix-broken -y
sleep 1

echo "copy usb rules"
cp 99-xvisio.rules /etc/udev/rules.d/
udevadm control --reload-rules && udevadm trigger
sleep 1

echo "install xvsdk"
dpkg -i $1
apt install -y --fix-broken
sleep 1

echo "cp ros2 wrapper"
mkdir -p ~/ros2_ws/src
cp -r /usr/share/ros2-wrapper/xv_ros2_msgs ~/ros2_ws/src
cp -r /usr/share/ros2-wrapper/xv_sdk_ros2 ~/ros2_ws/src

echo "compile ros2 wrapper"
cd ~/ros2_ws
source /opt/ros/galactic/setup.bash
colcon build  --packages-select xv_ros2_msgs
colcon build  --packages-select xv_sdk_ros2 --cmake-args -DXVSDK_INCLUDE_DIRS="/usr/include/xvsdk" -DXVSDK_LIBRARIES="/usr/lib/libxvsdk.so"
. install/setup.bash
chmod 777 -R ~/ros2_ws
