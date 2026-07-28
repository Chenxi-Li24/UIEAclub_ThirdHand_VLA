"""
Pydantic models for all configuration domains.

Each YAML config file maps to one Pydantic BaseModel.
Validation happens at load time (fail-fast).
"""

from pydantic import BaseModel, Field
from typing import Optional, Literal


class JointLimits(BaseModel):
    min_degrees: tuple[float, ...] = (-180, -155, -80, -180, -100, -360)
    max_degrees: tuple[float, ...] = (180, 155, 180, 180, 100, 360)


class GripperConfig(BaseModel):
    model: str = "TypeFZ"
    open_distance_mm: float = 60.0
    close_distance_mm: float = 0.0
    force: float = 0.5


class EStopConfig(BaseModel):
    method: str = "keyboard"
    keyboard_key: str = "space"
    gpio_pin: Optional[int] = None


class RobotConfig(BaseModel):
    model: str = "Lumos Touch R1"
    model_number: int = Field(default=0, ge=0, le=10)
    can_interface: str = "can0"
    can_bitrate: int = 1_000_000
    joint_limits: JointLimits = Field(default_factory=JointLimits)
    tcp_offset_m: tuple[float, float, float] = (0, 0, 0.155)
    home_joints_deg: tuple[float, ...] = (0, -30, -60, -90, 0, 0)
    default_speed: float = 0.3
    default_acceleration: float = 0.5
    gripper: GripperConfig = Field(default_factory=GripperConfig)
    estop: EStopConfig = Field(default_factory=EStopConfig)


class CameraConfig(BaseModel):
    model: Literal["std", "lite"] = "std"
    device_path: str = "/dev/video0"
    width: int = 1280
    height: int = 720
    fps: int = 30
    pixel_format: str = "RGB"
    calibration_file: Optional[str] = None
    camera_model: Literal["seucm", "fisheye", "pinhole"] = "seucm"
    depth_enabled: bool = False
    depth_width: int = 640
    depth_height: int = 480
    depth_fps: int = 15
    depth_unit: str = "mm"
    depth_invalid_value: int = 0
    tof_extrinsics: Optional[list[list[float]]] = None


class Bounds(BaseModel):
    x: tuple[float, float] = (-0.3, 0.5)
    y: tuple[float, float] = (-0.4, 0.4)
    z: tuple[float, float] = (-0.05, 0.4)


class DeskPlane(BaseModel):
    normal: tuple[float, float, float] = (0, 0, 1)
    offset_m: float = 0.0


class WorkspaceConfig(BaseModel):
    bounds_m: Bounds = Field(default_factory=Bounds)
    desk_plane: DeskPlane = Field(default_factory=DeskPlane)
    keep_out_zones: list[dict] = Field(default_factory=list)
    max_linear_speed_ms: float = 0.5
    max_joint_speed_degs: float = 90.0
    motion_timeout_s: float = 10.0


class ASRConfig(BaseModel):
    engine: str = "faster-whisper"
    model_size: str = "small"
    language: str = "zh"
    device: str = "cpu"
    compute_type: str = "int8"
    sample_rate: int = 16000
    vad_enabled: bool = True


class NLUConfig(BaseModel):
    engine: str = "local"
    local_model: Optional[str] = None
    intent_labels: list[str] = Field(default_factory=lambda: [
        "start_task", "stop", "pause", "resume", "emergency_stop", "go_home", "jog"
    ])


class TTSConfig(BaseModel):
    engine: str = "edge-tts"
    voice: str = "zh-CN-XiaoxiaoNeural"
    rate: str = "+0%"
    volume: str = "+0%"
    device: str = "cpu"


class MicConfig(BaseModel):
    device_index: Optional[int] = None
    chunk_size: int = 1024
    channels: int = 1


class AsrTtsConfig(BaseModel):
    asr: ASRConfig = Field(default_factory=ASRConfig)
    nlu: NLUConfig = Field(default_factory=NLUConfig)
    tts: TTSConfig = Field(default_factory=TTSConfig)
    microphone: MicConfig = Field(default_factory=MicConfig)


class VLATriggerConfig(BaseModel):
    multiple_objects: bool = True
    error_recovery: bool = True
    idle_query: bool = True
    confidence_threshold: float = 0.7


class VLAConfig(BaseModel):
    provider: Literal["anthropic", "deepseek", "openai"] = "anthropic"
    model: str = "claude-sonnet-4-20250514"
    max_tokens: int = 4096
    image_max_side: int = 1024
    image_quality: int = 85
    image_format: str = "jpeg"
    history_size: int = 20
    trigger_on: VLATriggerConfig = Field(default_factory=VLATriggerConfig)


class ServerConfig(BaseModel):
    host: str = "0.0.0.0"
    port: int = 8000
    reload: bool = False
    workers: int = 1


class CORSConfig(BaseModel):
    origins: list[str] = Field(default_factory=lambda: ["*"])


class WSConfig(BaseModel):
    ping_interval: int = 30
    ping_timeout: int = 10
    max_message_size_mb: int = 16


class VideoConfig(BaseModel):
    method: str = "mjpeg"
    max_fps: int = 15
    quality: int = 70
    overlay_detections: bool = True


class Robot3DConfig(BaseModel):
    urdf_path: Optional[str] = None


class WebConfig(BaseModel):
    server: ServerConfig = Field(default_factory=ServerConfig)
    cors: CORSConfig = Field(default_factory=CORSConfig)
    websocket: WSConfig = Field(default_factory=WSConfig)
    video: VideoConfig = Field(default_factory=VideoConfig)
    robot_3d: Robot3DConfig = Field(default_factory=Robot3DConfig)


class AppConfig(BaseModel):
    """Master config aggregating all domains."""
    robot: RobotConfig = Field(default_factory=RobotConfig)
    camera: CameraConfig = Field(default_factory=CameraConfig)
    workspace: WorkspaceConfig = Field(default_factory=WorkspaceConfig)
    asr_tts: Optional[AsrTtsConfig] = None
    vla: Optional[VLAConfig] = None
    web: WebConfig = Field(default_factory=WebConfig)
