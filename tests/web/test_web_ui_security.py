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


def test_camera_test_page_exposes_both_camera_roles_without_motion_controls() -> None:
    source = (
        Path(__file__).parents[2] / "web-control/web/camera-test.html"
    ).read_text(encoding="utf-8")

    assert 'src="/camera_lumos"' in source
    assert 'src="/camera"' in source
    assert "Lumos" in source
    assert "D435" in source
    assert "grasp_object" not in source


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
