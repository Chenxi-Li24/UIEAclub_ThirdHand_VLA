"""Static browser UI security contracts."""

from pathlib import Path


def test_dynamic_robot_data_is_not_rendered_with_inner_html() -> None:
    source = (
        Path(__file__).parents[2] / "web-control/web/js/main.js"
    ).read_text(encoding="utf-8")

    assert "row.innerHTML" not in source
    assert "list.innerHTML" not in source


def test_detection_ui_only_enables_server_authorized_targets() -> None:
    source = (
        Path(__file__).parents[2] / "web-control/web/js/main.js"
    ).read_text(encoding="utf-8")

    assert "obj.actionable === true" in source
    assert "bx: obj.bx" not in source
    assert "by: obj.by" not in source
    assert "bz: obj.bz" not in source
    assert ":3001/camera_lumos" not in source
    assert "const lumosStreamUrl = '/camera_lumos'" in source


def test_camera_test_page_exposes_both_camera_roles_with_id_only_active_view() -> None:
    source = (
        Path(__file__).parents[2] / "web-control/web/camera-test.html"
    ).read_text(encoding="utf-8")

    assert 'data-stream="/camera_lumos"' in source
    assert 'data-overlay-stream="/camera_lumos_vision"' in source
    assert 'data-stream="/camera"' in source
    assert 'src="/camera_lumos_vision"' not in source
    assert 'src="/camera"' not in source
    assert "Lumos" in source
    assert "D435" in source
    assert "canonical RGB / identity" in source
    assert "metric depth / debug RGB" in source
    assert "/api/vision/status" in source
    assert "blockers" in source
    assert "robotExecutionEnabled" in source
    assert "activeViewExecutionEnabled" in source
    assert "观察建议" in source
    assert "D435 深度质量" in source
    assert "稳定样本" in source
    assert "剩余精调" in source
    assert "grasp_object" not in source
    assert "start_active_view" in source
    assert "confirm_active_view_step" in source
    assert "cancel_active_view" in source
    assert "GRASP_PREVIEW" in source
    assert "每一步均需人工确认" in source
    for marker in (
        "实例轮廓",
        "持久 ID",
        "三维坐标",
        "目标状态",
        "抓取点",
        "允许抓取",
    ):
        assert marker in source
    assert 'id="target-diagnostics"' in source
    assert "targetDiagnostics.replaceChildren" in source
    assert "targetDiagnostics.innerHTML" not in source
    for forbidden in (
        "jointsDeg",
        "deltaBaseM",
        "tcp_position",
        "euler",
        "safetyApproved",
    ):
        assert forbidden not in source
    assert "move_joint" not in source
    assert "move_l" not in source
    assert "method: 'POST'" not in source
    assert "contenteditable" not in source


def test_camera_page_websocket_commands_contain_ids_only() -> None:
    source = (
        Path(__file__).parents[2] / "web-control/web/camera-test.html"
    ).read_text(encoding="utf-8")

    assert "{ cmd: 'start_active_view', identityId }" in source
    assert "{ cmd: 'confirm_active_view_step', sessionId, proposalId }" in source
    assert "{ cmd: 'cancel_active_view', sessionId }" in source


def test_camera_page_exposes_real_identity_memory_diagnostics() -> None:
    source = (
        Path(__file__).parents[2] / "web-control/web/camera-test.html"
    ).read_text(encoding="utf-8")

    for marker in (
        "DINO 原型相似度",
        "REMIND work / stable",
        "关联代价 / 原因",
    ):
        assert marker in source


def test_proxy_exposes_read_only_vision_status_and_overlay_routes() -> None:
    source = (
        Path(__file__).parents[2] / "web-control/server/proxy.js"
    ).read_text(encoding="utf-8")

    assert "'/api/vision/status'" in source
    assert "'/camera_lumos_vision'" in source
    assert "getVisionMjpegStream" in source
    assert "'/camera_d435_raw'" in source
    assert "getD435RawMjpegStream" in source


def test_proxy_keeps_active_view_coordinates_out_of_browser_dispatch() -> None:
    source = (
        Path(__file__).parents[2] / "web-control/server/proxy.js"
    ).read_text(encoding="utf-8")

    assert "sendRobot: sendActiveViewRobotCommand" in source
    assert "parseActiveViewBrowserCommand(message)" in source
    assert "trustedTargets: visionStatus.trustedTargets(Date.now())" in source
    assert "const confirmed = activeView.confirm({" in source
    assert "cameraBridge.on('active_view_move_proposal'" in source
    assert "broadcast({ type: 'active_view_move_ready', ...control })" in source
    assert "activeViewIsActive()" in source


def test_vision_robot_execution_is_hard_locked_in_this_release() -> None:
    source = (
        Path(__file__).parents[2] / "web-control/server/config.js"
    ).read_text(encoding="utf-8")

    assert "robotExecutionEnabled: false" in source
    assert "VISION_ROBOT_EXECUTION_ENABLED" not in source


def test_lumos_proxy_has_a_safe_default_upstream() -> None:
    source = (
        Path(__file__).parents[2] / "web-control/server/proxy.js"
    ).read_text(encoding="utf-8")

    assert "http://127.0.0.1:3001/camera_lumos" in source


def test_calibration_capture_page_has_one_bounded_non_robot_action() -> None:
    root = Path(__file__).parents[2]
    page = (root / "web-control/web/calibration-capture.html").read_text(encoding="utf-8")
    client = (root / "web-control/web/calibration-capture.js").read_text(encoding="utf-8")
    source = page + client

    assert 'data-preview="/api/calibration-preview/lumos.jpg"' in page
    assert 'data-preview="/api/calibration-preview/d435.jpg"' in page
    assert page.count("<button") == 1
    assert "'/api/calibration/capture-fit'" in client
    assert "'/api/calibration/solve'" in client
    assert "'/api/calibration/capture'" in client
    assert "method: 'POST'" in client
    assert "拟合姿态" in page
    assert "独立验证" in page
    assert "replaceChildren" in client
    assert "innerHTML" not in source
    assert "WebSocket" not in source
    assert "contenteditable" not in source
    for forbidden in ("move_joint", "move_l", "gripper", "joints_deg", "tcp_position"):
        assert forbidden not in source.lower()


def test_proxy_mounts_isolated_calibration_capture_router() -> None:
    source = (
        Path(__file__).parents[2] / "web-control/server/proxy.js"
    ).read_text(encoding="utf-8")

    assert "CalibrationCaptureService" in source
    assert "createCalibrationCaptureRouter" in source
    assert "app.use('/api/calibration'" in source


def test_calibration_completion_page_is_single_action_and_read_only() -> None:
    root = Path(__file__).parents[2]
    page = (root / "web-control/web/calibration-completion.html").read_text(
        encoding="utf-8"
    )
    client = (root / "web-control/web/calibration-completion.js").read_text(
        encoding="utf-8"
    )
    source = (page + client).lower()

    assert page.count("<button") == 1
    assert 'data-preview="/api/calibration-preview/d435.jpg"' in page
    assert "/api/calibration-completion/capture-handeye" in client
    assert "/api/calibration-completion/solve-handeye" in client
    assert "/api/calibration-completion/capture-table" in client
    assert "/api/calibration-completion/finalize" in client
    assert "标定板保持固定" in client
    assert "平放" in client
    assert "手动" in page
    assert "replaceChildren" in client
    assert "innerhtml" not in source
    assert "websocket" not in source
    assert "contenteditable" not in source
    for forbidden in (
        "move_joint",
        "move_l",
        "gripper",
        "joints_deg",
        "tcp_position",
        "delta_base_m",
    ):
        assert forbidden not in source


def test_proxy_mounts_isolated_calibration_completion_router() -> None:
    source = (
        Path(__file__).parents[2] / "web-control/server/proxy.js"
    ).read_text(encoding="utf-8")

    assert "CalibrationCompletionService" in source
    assert "createCalibrationCompletionRouter" in source
    assert "app.use('/api/calibration-completion'" in source
