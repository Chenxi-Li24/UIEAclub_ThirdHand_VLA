# XVisio RGB-D Driver

This directory owns the unified project's XVisio camera boundary. It has no robot
imports and cannot open CAN.

## Layout

- `native/xvisio_rgbd_stream.cpp`: the reviewed XVisio SDK process. It captures
  color and ToF frames, registers depth into the color image, and writes protocol
  v2 packets to an inherited Unix socket.
- `native/CMakeLists.txt`: links only the system `xvsdk`, OpenCV, and pthread.
- `src/xvisio_stream.py`: validates protocol headers, camera identity, payload
  sizes, sequence numbers, and monotonic timestamps before exposing NumPy frames.
- `scripts/build.sh`: builds into ignored
  `runtime/build/xvisio/xvisio_rgbd_stream`.

## Build

The Ubuntu host must provide CMake, a C++14 compiler, OpenCV development files,
and the XVisio SDK CMake package.

```bash
drivers/xvisio/scripts/build.sh
```

Building does not open the USB camera. Only one running native process may own the
XVisio device. The Vision Service is the intended owner.

## Packet Contract

Every packet contains an 88-byte little-endian header followed by RGB8, float32
metric depth, and float32 XYZ arrays. The Python side rejects unknown magic or
version values, frames larger than 1920x1080, inconsistent byte counts, a serial
different from the configured camera, and non-increasing sequence or timestamps.
Reads have a bounded timeout so a silent native process becomes a visible service
error instead of hanging startup forever.
