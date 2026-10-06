import base64
import json
from pathlib import Path
import sys
import time
import urllib.request

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from dummy.person_follow.runtime import PersonFollowRuntime
from dummy.person_follow.telemetry import FollowTelemetryServer, observation_snapshot
from dummy.tracker import Target


def test_window_packet_is_the_controller_observation_and_server_closes():
    runtime = PersonFollowRuntime(None)
    image = np.zeros((48, 64, 3), dtype=np.uint8)
    runtime.publish(Target(True, 32, 24, 64, 48, .9, "face", time.time()),
                    frame=image, frame_id=7, debug={"bbox": (12, 4, 30, 35)})
    runtime.metrics.update(observation_sequence=1, request_id="control-1")
    frame, snapshot = observation_snapshot(runtime)
    assert frame is image and snapshot["used_by_last_command"]
    assert not snapshot["motion_enabled"] and snapshot["robot_joints_deg"] is None
    assert snapshot["preview_joints_deg"] == runtime.joints
    runtime.adapter = object()
    _, measured = observation_snapshot(runtime)
    assert measured["motion_enabled"] and measured["robot_joints_deg"] == runtime.joints
    assert measured["preview_joints_deg"] is None
    runtime.adapter = None
    server = FollowTelemetryServer(runtime, port=0)
    server.start()
    try:
        with urllib.request.urlopen(f'http://127.0.0.1:{server.server.server_port}/api/frame') as response:
            packet = json.load(response)
        assert packet["state"]["frame_id"] == 7
        assert packet["state"]["control"]["request_id"] == "control-1"
        assert base64.b64decode(packet["jpeg_base64"]).startswith(b'\xff\xd8')
    finally:
        server.close()
    assert not server.thread.is_alive()
