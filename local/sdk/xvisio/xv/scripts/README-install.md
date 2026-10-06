# 一键安装脚本介绍

## install-ros1.sh

用于一键安装xvsdk及ros1功能包，运行方法： sudo ./install-ros1.sh + xvsdk安装包。例如：

sudo -E ./install-ros1.sh XVSDK_focal_amd64_1112.deb

## install-ros2.sh

用于一键安装xvsdk及ros2功能包，运行方法： sudo ./install-ros2.sh + xvsdk安装包。例如：

sudo -E ./install-ros2.sh XVSDK_focal_amd64_1112.deb

## install-python.sh

用于一键安装xvsdk及python运行环境，运行方法： sudo ./install-python.sh + xvsdk安装包。例如：

sudo -E ./install-python.sh XVSDK_focal_amd64_1112.deb

## multi-support.sh

用于扩展usb带宽，支持多设备运行环境。运行方法：sudo -E ./multi-support.sh

注意：该脚本运行一次，永久修改，该脚本只适用于使用默认带宽，没有修改过带宽参数的机器，修改后会自动重启电脑，根据自身需求使用。
