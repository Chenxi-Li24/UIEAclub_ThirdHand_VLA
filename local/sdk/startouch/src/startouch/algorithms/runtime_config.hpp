#pragma once

#include <cstddef>
#include <string>

namespace startouch::algorithms {

struct IkFallbackConfig {
    bool enabled = false;
    double position_tolerance_m = 0.005;
    std::size_t max_candidates = 32;
    double max_time_ms = 3.0;
};

std::string resolve_robot_kinematics_config_path();
std::string resolve_robot_urdf_path();
bool motion_planning_debug_enabled();
bool ik_diagnostics_debug_enabled();
const IkFallbackConfig& ik_fallback_config();

}  // namespace startouch::algorithms
