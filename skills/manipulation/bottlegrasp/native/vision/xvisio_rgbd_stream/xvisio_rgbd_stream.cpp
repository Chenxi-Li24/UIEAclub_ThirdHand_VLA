#include <xv-sdk.h>
#include <opencv2/imgproc.hpp>

#include <algorithm>
#include <array>
#include <cerrno>
#include <chrono>
#include <cmath>
#include <condition_variable>
#include <csignal>
#include <cstdint>
#include <cstring>
#include <iostream>
#include <limits>
#include <memory>
#include <mutex>
#include <string>
#include <thread>
#include <unistd.h>
#include <vector>

namespace {

constexpr std::int64_t kMinimumFramePeriodNs = 66'000'000;
volatile std::sig_atomic_t stop_requested = 0;

#pragma pack(push, 1)
struct PacketHeader {
    char magic[8];
    std::uint32_t version;
    std::uint32_t header_bytes;
    std::uint32_t width;
    std::uint32_t height;
    std::uint64_t sequence;
    std::uint64_t monotonic_ns;
    std::uint32_t rgb_bytes;
    std::uint32_t depth_bytes;
    std::uint32_t xyz_bytes;
    std::uint32_t flags;
    char serial[32];
};
#pragma pack(pop)

static_assert(sizeof(PacketHeader) == 88, "unexpected RGB-D packet header size");

struct Frame {
    std::uint32_t width = 0;
    std::uint32_t height = 0;
    std::uint64_t sequence = 0;
    std::uint64_t monotonic_ns = 0;
    std::vector<std::uint8_t> rgb;
    std::vector<float> depth_m;
    std::vector<float> xyz_camera_m;
};

struct RegisteredGeometry {
    std::vector<float> depth_m;
    std::vector<float> xyz_camera_m;
};

struct ColorFrame {
    std::size_t width = 0;
    std::size_t height = 0;
    std::vector<std::uint8_t> rgb;
};

struct CameraGeometry {
    std::shared_ptr<xv::CameraModel> color_model;
    std::shared_ptr<xv::CameraModel> tof_model;
    xv::Matrix3d r_imu_from_color{};
    xv::Vector3d t_imu_from_color{};
    xv::Matrix3d r_imu_from_tof{};
    xv::Vector3d t_imu_from_tof{};
    bool ready = false;
};

struct LatestFrame {
    std::mutex mutex;
    std::condition_variable ready;
    Frame frame;
    std::uint64_t published_sequence = 0;
    std::int64_t last_capture_ns = 0;
    ColorFrame color;
    CameraGeometry geometry;
    std::string camera_serial;
    bool has_color = false;
    bool stopping = false;
};

std::shared_ptr<xv::CameraModel> find_camera_model(
    const std::vector<xv::Calibration>& calibrations,
    int width,
    int height,
    xv::Matrix3d& rotation,
    xv::Vector3d& translation) {
    for (const auto& calibration : calibrations) {
        for (const auto& model : calibration.camerasModel) {
            if (model && model->width() == width && model->height() == height) {
                rotation = calibration.pose.rotation();
                translation = calibration.pose.translation();
                return model;
            }
        }
    }
    return {};
}

std::array<double, 3> rotate(
    const xv::Matrix3d& rotation,
    const std::array<double, 3>& point) {
    return {{
        rotation[0] * point[0] + rotation[1] * point[1] +
            rotation[2] * point[2],
        rotation[3] * point[0] + rotation[4] * point[1] +
            rotation[5] * point[2],
        rotation[6] * point[0] + rotation[7] * point[1] +
            rotation[8] * point[2],
    }};
}

std::array<double, 3> inverse_transform(
    const xv::Matrix3d& rotation,
    const xv::Vector3d& translation,
    const std::array<double, 3>& point) {
    const std::array<double, 3> shifted{{
        point[0] - translation[0],
        point[1] - translation[1],
        point[2] - translation[2],
    }};
    return {{
        rotation[0] * shifted[0] + rotation[3] * shifted[1] +
            rotation[6] * shifted[2],
        rotation[1] * shifted[0] + rotation[4] * shifted[1] +
            rotation[7] * shifted[2],
        rotation[2] * shifted[0] + rotation[5] * shifted[1] +
            rotation[8] * shifted[2],
    }};
}

struct CropMapping {
    int crop_x = 0;
    int crop_y = 0;
    int crop_width = 0;
    int crop_height = 0;
    double scale_x = 0.0;
    double scale_y = 0.0;
};

CropMapping crop_mapping(
    std::size_t source_width,
    std::size_t source_height,
    std::size_t target_width,
    std::size_t target_height) {
    CropMapping mapping;
    const double target_aspect =
        static_cast<double>(target_width) / static_cast<double>(target_height);
    mapping.crop_width = static_cast<int>(source_width);
    mapping.crop_height = static_cast<int>(source_height);
    if (static_cast<double>(source_width) / source_height > target_aspect) {
        mapping.crop_width = std::max(
            1, static_cast<int>(std::lround(source_height * target_aspect)));
    } else {
        mapping.crop_height = std::max(
            1, static_cast<int>(std::lround(source_width / target_aspect)));
    }
    mapping.crop_x = (static_cast<int>(source_width) - mapping.crop_width) / 2;
    mapping.crop_y = (static_cast<int>(source_height) - mapping.crop_height) / 2;
    mapping.scale_x = static_cast<double>(target_width) / mapping.crop_width;
    mapping.scale_y = static_cast<double>(target_height) / mapping.crop_height;
    return mapping;
}

void request_stop(int) {
    stop_requested = 1;
}

std::int64_t monotonic_ns() {
    return std::chrono::duration_cast<std::chrono::nanoseconds>(
               std::chrono::steady_clock::now().time_since_epoch())
        .count();
}

bool write_all(int fd, const void* data, std::size_t size) {
    const auto* cursor = static_cast<const std::uint8_t*>(data);
    while (size > 0) {
        const ssize_t written = ::write(fd, cursor, size);
        if (written > 0) {
            cursor += written;
            size -= static_cast<std::size_t>(written);
            continue;
        }
        if (written < 0 && errno == EINTR) {
            continue;
        }
        return false;
    }
    return true;
}

void receive_color(LatestFrame& latest, const xv::ColorImage& source) {
    if (source.width == 0 || source.height == 0 || !source.data) {
        return;
    }
    try {
        const xv::RgbImage decoded = source.toRgb();
        if (decoded.width == 0 || decoded.height == 0 || !decoded.data) {
            return;
        }
        ColorFrame frame;
        frame.width = decoded.width;
        frame.height = decoded.height;
        const std::size_t bytes = decoded.width * decoded.height * 3;
        frame.rgb.assign(decoded.data.get(), decoded.data.get() + bytes);
        std::lock_guard<std::mutex> lock(latest.mutex);
        if (!latest.stopping) {
            latest.color = std::move(frame);
            latest.has_color = true;
        }
    } catch (const std::exception&) {
        // A malformed color frame must not stop the depth callback thread.
    }
}

std::vector<std::uint8_t> resize_color(
    const ColorFrame& source,
    std::size_t target_width,
    std::size_t target_height) {
    if (source.width == 0 || source.height == 0 || source.rgb.empty() ||
        target_width == 0 || target_height == 0) {
        return {};
    }
    const cv::Mat source_rgb(
        static_cast<int>(source.height),
        static_cast<int>(source.width),
        CV_8UC3,
        const_cast<std::uint8_t*>(source.rgb.data()));
    const CropMapping mapping = crop_mapping(
        source.width, source.height, target_width, target_height);
    cv::Mat resized;
    cv::resize(
        source_rgb(cv::Rect(
            mapping.crop_x,
            mapping.crop_y,
            mapping.crop_width,
            mapping.crop_height)),
        resized,
        cv::Size(static_cast<int>(target_width), static_cast<int>(target_height)),
        0.0,
        0.0,
        cv::INTER_LINEAR);
    const std::size_t bytes = target_width * target_height * 3;
    std::vector<std::uint8_t> result(bytes);
    std::memcpy(result.data(), resized.data, bytes);
    return result;
}

RegisteredGeometry register_depth_to_color(
    const CameraGeometry& geometry,
    const ColorFrame& color,
    const std::vector<float>& tof_depth_m,
    std::size_t tof_width,
    std::size_t tof_height,
    std::size_t output_width,
    std::size_t output_height) {
    const float nan = std::numeric_limits<float>::quiet_NaN();
    RegisteredGeometry registered;
    registered.depth_m.assign(output_width * output_height, nan);
    registered.xyz_camera_m.assign(output_width * output_height * 3, nan);
    if (!geometry.ready || !geometry.color_model || !geometry.tof_model ||
        geometry.color_model->width() != static_cast<int>(color.width) ||
        geometry.color_model->height() != static_cast<int>(color.height) ||
        geometry.tof_model->width() != static_cast<int>(tof_width) ||
        geometry.tof_model->height() != static_cast<int>(tof_height)) {
        return registered;
    }
    const CropMapping mapping = crop_mapping(
        color.width, color.height, output_width, output_height);
    for (std::size_t row = 0; row < tof_height; ++row) {
        for (std::size_t column = 0; column < tof_width; ++column) {
            const float range_m = tof_depth_m[row * tof_width + column];
            if (!std::isfinite(range_m) || range_m <= 0.01F || range_m > 9.9F) {
                continue;
            }
            const std::array<double, 2> tof_pixel{{
                static_cast<double>(column), static_cast<double>(row)}};
            std::array<double, 3> tof_ray{{0.0, 0.0, 0.0}};
            if (!geometry.tof_model->raytrace(tof_pixel.data(), tof_ray.data())) {
                continue;
            }
            const std::array<double, 3> point_tof{{
                tof_ray[0] * range_m,
                tof_ray[1] * range_m,
                tof_ray[2] * range_m,
            }};
            auto point_imu = rotate(geometry.r_imu_from_tof, point_tof);
            point_imu[0] += geometry.t_imu_from_tof[0];
            point_imu[1] += geometry.t_imu_from_tof[1];
            point_imu[2] += geometry.t_imu_from_tof[2];
            const auto point_color = inverse_transform(
                geometry.r_imu_from_color,
                geometry.t_imu_from_color,
                point_imu);
            if (point_color[2] <= 0.0) {
                continue;
            }
            std::array<double, 2> color_pixel{{0.0, 0.0}};
            if (!geometry.color_model->project(
                    point_color.data(), color_pixel.data())) {
                continue;
            }
            const double output_x =
                (color_pixel[0] - mapping.crop_x) * mapping.scale_x;
            const double output_y =
                (color_pixel[1] - mapping.crop_y) * mapping.scale_y;
            const int x = static_cast<int>(std::lround(output_x));
            const int y = static_cast<int>(std::lround(output_y));
            if (x < 0 || y < 0 || x >= static_cast<int>(output_width) ||
                y >= static_cast<int>(output_height)) {
                continue;
            }
            const std::size_t output_index =
                static_cast<std::size_t>(y) * output_width +
                static_cast<std::size_t>(x);
            float& destination = registered.depth_m[output_index];
            const float color_z_m = static_cast<float>(point_color[2]);
            if (!std::isfinite(destination) || color_z_m < destination) {
                destination = color_z_m;
                registered.xyz_camera_m[output_index * 3] =
                    static_cast<float>(point_color[0]);
                registered.xyz_camera_m[output_index * 3 + 1] =
                    static_cast<float>(point_color[1]);
                registered.xyz_camera_m[output_index * 3 + 2] = color_z_m;
            }
        }
    }
    return registered;
}

void receive_rgbd(LatestFrame& latest, const xv::DepthColorImage& source) {
    if (source.width == 0 || source.height == 0 || !source.data) {
        return;
    }
    const std::int64_t receipt_ns = monotonic_ns();
    ColorFrame color;
    {
        std::lock_guard<std::mutex> lock(latest.mutex);
        if (latest.stopping || !latest.has_color ||
            (latest.last_capture_ns > 0 &&
             receipt_ns - latest.last_capture_ns < kMinimumFramePeriodNs)) {
            return;
        }
        latest.last_capture_ns = receipt_ns;
        color = latest.color;
    }

    Frame frame;
    frame.width = static_cast<std::uint32_t>(source.width);
    frame.height = static_cast<std::uint32_t>(source.height);
    frame.monotonic_ns = static_cast<std::uint64_t>(receipt_ns);
    const std::size_t pixels = source.width * source.height;
    frame.rgb = resize_color(color, source.width, source.height);
    if (frame.rgb.size() != pixels * 3) {
        return;
    }
    std::vector<float> tof_depth_m(pixels);

    const auto* packed = reinterpret_cast<const std::uint8_t*>(source.data.get());
    constexpr std::size_t stride = 3 + sizeof(float);
    for (std::size_t index = 0; index < pixels; ++index) {
        const auto* pixel = packed + index * stride;
        std::memcpy(tof_depth_m.data() + index, pixel + 3, sizeof(float));
    }
    auto registered = register_depth_to_color(
        latest.geometry,
        color,
        tof_depth_m,
        source.width,
        source.height,
        source.width,
        source.height);
    frame.depth_m = std::move(registered.depth_m);
    frame.xyz_camera_m = std::move(registered.xyz_camera_m);

    {
        std::lock_guard<std::mutex> lock(latest.mutex);
        frame.sequence = ++latest.published_sequence;
        latest.frame = std::move(frame);
    }
    latest.ready.notify_one();
}

void send_frames(LatestFrame& latest, int output_fd) {
    std::uint64_t sent_sequence = 0;
    while (true) {
        Frame frame;
        {
            std::unique_lock<std::mutex> lock(latest.mutex);
            latest.ready.wait(lock, [&] {
                return latest.stopping || latest.published_sequence > sent_sequence;
            });
            if (latest.stopping) {
                return;
            }
            frame = latest.frame;
            sent_sequence = frame.sequence;
        }

        PacketHeader header{};
        const std::array<char, 8> magic{{'X', 'V', 'R', 'G', 'B', 'D', '2', '\0'}};
        std::copy(magic.begin(), magic.end(), header.magic);
        header.version = 2;
        header.header_bytes = sizeof(PacketHeader);
        header.width = frame.width;
        header.height = frame.height;
        header.sequence = frame.sequence;
        header.monotonic_ns = frame.monotonic_ns;
        header.rgb_bytes = static_cast<std::uint32_t>(frame.rgb.size());
        header.depth_bytes = static_cast<std::uint32_t>(
            frame.depth_m.size() * sizeof(float));
        header.xyz_bytes = static_cast<std::uint32_t>(
            frame.xyz_camera_m.size() * sizeof(float));
        header.flags = 0;
        const std::size_t serial_bytes =
            std::min(latest.camera_serial.size(), sizeof(header.serial) - 1);
        std::memcpy(
            header.serial, latest.camera_serial.data(), serial_bytes);
        if (!write_all(output_fd, &header, sizeof(header)) ||
            !write_all(output_fd, frame.rgb.data(), frame.rgb.size()) ||
            !write_all(
                output_fd,
                frame.depth_m.data(),
                frame.depth_m.size() * sizeof(float)) ||
            !write_all(
                output_fd,
                frame.xyz_camera_m.data(),
                frame.xyz_camera_m.size() * sizeof(float))) {
            stop_requested = 1;
            return;
        }
    }
}

}  // namespace

int main(int argc, char** argv) try {
    if (argc != 2) {
        std::cerr << "usage: xvisio_rgbd_stream OUTPUT_FD\n";
        return 2;
    }
    const int output_fd = std::stoi(argv[1]);
    if (output_fd < 3) {
        std::cerr << "invalid output fd\n";
        return 2;
    }

    std::signal(SIGINT, request_stop);
    std::signal(SIGTERM, request_stop);
    std::signal(SIGPIPE, SIG_IGN);

    auto devices = xv::getDevices(10.0, "");
    if (devices.empty()) {
        std::cerr << "xvisio: no device found\n";
        return 3;
    }
    const auto device = devices.begin()->second;
    const auto color = device->colorCamera();
    const auto tof = device->tofCamera();
    if (!color || !tof) {
        std::cerr << "xvisio: RGB or ToF stream unavailable\n";
        return 4;
    }

    LatestFrame latest;
    latest.camera_serial = devices.begin()->first;
    if (latest.camera_serial.empty() ||
        latest.camera_serial.size() >= sizeof(PacketHeader::serial)) {
        std::cerr << "xvisio: invalid device serial\n";
        return 5;
    }
    const auto color_calibrations = color->calibration();
    const auto tof_calibrations = tof->calibration();
    latest.geometry.color_model = find_camera_model(
        color_calibrations,
        1280,
        1280,
        latest.geometry.r_imu_from_color,
        latest.geometry.t_imu_from_color);
    latest.geometry.tof_model = find_camera_model(
        tof_calibrations,
        640,
        480,
        latest.geometry.r_imu_from_tof,
        latest.geometry.t_imu_from_tof);
    latest.geometry.ready =
        static_cast<bool>(latest.geometry.color_model) &&
        static_cast<bool>(latest.geometry.tof_model);
    if (!latest.geometry.ready) {
        std::cerr << "xvisio: calibrated RGB/ToF camera models unavailable\n";
        return 5;
    }
    std::thread writer(send_frames, std::ref(latest), output_fd);
    device->enableSync(false);
    color->setResolution(xv::ColorCamera::Resolution::RGB_1920x1080);
    const int color_id = color->registerCallback(
        [&](const xv::ColorImage& frame) { receive_color(latest, frame); });
    color->start();
    if (!tof->setLibWorkMode(static_cast<xv::TofCamera::SonyTofLibMode>(3))) {
        std::cerr << "xvisio: failed to select default Sony ToF mode\n";
    }
    std::this_thread::sleep_for(std::chrono::milliseconds(500));
    tof->start();
    const int rgbd_id = tof->registerColorDepthImageCallback(
        [&](const xv::DepthColorImage& frame) { receive_rgbd(latest, frame); });

    while (!stop_requested) {
        std::this_thread::sleep_for(std::chrono::milliseconds(50));
    }

    tof->stop();
    tof->unregisterColorDepthImageCallback(rgbd_id);
    color->stop();
    color->unregisterCallback(color_id);
    {
        std::lock_guard<std::mutex> lock(latest.mutex);
        latest.stopping = true;
    }
    latest.ready.notify_all();
    writer.join();
    ::close(output_fd);
    return 0;
} catch (const std::exception& error) {
    std::cerr << "xvisio: " << error.what() << '\n';
    return 10;
}
