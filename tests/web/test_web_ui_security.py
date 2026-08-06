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
