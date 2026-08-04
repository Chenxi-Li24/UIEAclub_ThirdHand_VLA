"""Static browser UI security contracts."""

from pathlib import Path


def test_dynamic_robot_data_is_not_rendered_with_inner_html() -> None:
    source = (
        Path(__file__).parents[2] / "web-control/web/js/main.js"
    ).read_text(encoding="utf-8")

    assert "row.innerHTML" not in source
    assert "list.innerHTML" not in source
