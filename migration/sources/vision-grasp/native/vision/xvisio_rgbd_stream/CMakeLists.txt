cmake_minimum_required(VERSION 3.5)
project(thirdhand_va_xvisio_rgbd_stream LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 14)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

find_package(xvsdk REQUIRED)
find_package(OpenCV REQUIRED)

add_executable(xvisio_rgbd_stream xvisio_rgbd_stream.cpp)
target_include_directories(
    xvisio_rgbd_stream
    PRIVATE
    ${xvsdk_INCLUDE_DIRS}
    ${xvsdk_INCLUDE_DIRS}/xvsdk
    ${OpenCV_INCLUDE_DIRS}
)
target_link_libraries(
    xvisio_rgbd_stream
    PRIVATE
    ${xvsdk_LIBRARIES}
    ${OpenCV_LIBS}
    pthread
)
