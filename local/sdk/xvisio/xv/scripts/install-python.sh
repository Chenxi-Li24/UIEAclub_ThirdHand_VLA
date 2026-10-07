#!/bin/bash

chmod 777 *

echo "install environment"
apt-get update
apt-get install -y tree g++ cmake cmake-curses-gui pkg-config autoconf libtool libudev-dev libjpeg-dev zlib1g-dev libopencv-dev rapidjson-dev libeigen3-dev libboost-thread-dev libboost-filesystem-dev libboost-system-dev libboost-program-options-dev libboost-date-time-dev liboctomap-dev doxygen libcxsparse3 libsuitesparse-dev
apt-get install --fix-broken -y
apt install -y software-properties-common
add-apt-repository -y ppa:deadsnakes/ppa
apt install -y python3.9
apt install -y python3-pip
pip install keyboard
sleep 1

echo "copy usb rules"
cp 99-xvisio.rules /etc/udev/rules.d/
udevadm control --reload-rules && udevadm trigger
sleep 1

echo "install xvsdk"
dpkg -i $1
apt install -y --fix-broken
sleep 1

