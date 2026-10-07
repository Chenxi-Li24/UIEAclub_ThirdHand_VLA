#!/bin/bash

chmod 777 *

echo "install environment"
apt-get update
apt-get install -y tree g++ cmake cmake-curses-gui pkg-config autoconf libtool libudev-dev libjpeg-dev zlib1g-dev libopencv-dev rapidjson-dev libeigen3-dev libboost-thread-dev libboost-filesystem-dev libboost-system-dev libboost-program-options-dev libboost-date-time-dev liboctomap-dev doxygen libcxsparse3 libsuitesparse-dev ros-noetic-ddynamic-reconfigure
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

echo "cp ros1 wrapper"
mkdir -p ~/catkin_ws/src
cp -r /usr/share/ros-wrapper/xv_sdk ~/catkin_ws/src/

echo "compile ros1 wrapper"
cd ~/catkin_ws/
rosdep install --from-paths src --ignore-src -r -y

source /opt/ros/noetic/setup.bash
source ${HOME}/catkin_ws/devel/setup.bash

catkin_make -DXVSDK_INCLUDE_DIRS="/usr/include/xvsdk" -DXVSDK_LIBRARIES="/usr/lib/libxvsdk.so"
chmod 777 -R ~/catkin_ws/

echo "source /opt/ros/noetic/setup.bash" >> ~/.bashrc
echo "source ${HOME}/catkin_ws/devel/setup.bash" >> ~/.bashrc
source ~/.bashrc

