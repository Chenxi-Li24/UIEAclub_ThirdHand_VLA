from __future__ import annotations

from pathlib import Path


def test_a3_generator_preserves_metric_tag_and_grid_dimensions(tmp_path: Path) -> None:
    script_path = Path(__file__).parents[2] / "scripts/vision/generate_aprilgrid_target.py"
    namespace: dict[str, object] = {
        "__name__": "generate_aprilgrid_target_test",
        "__file__": str(script_path),
    }
    exec(compile(script_path.read_text(encoding="utf-8"), script_path, "exec"), namespace)
    target = Path(__file__).parents[2] / "configs/vision/calibration/aprilgrid_6x6.yaml"
    output = tmp_path / "target.svg"

    metadata = namespace["generate_target"](target, output)

    assert metadata["page_width_mm"] == 297.0
    assert metadata["page_height_mm"] == 420.0
    assert metadata["tag_size_mm"] == 36.0
    assert metadata["grid_size_mm"] == 270.0
    svg = output.read_text(encoding="utf-8")
    assert 'width="297mm"' in svg
    assert 'height="420mm"' in svg
    assert svg.count('data-tag-id="') == 36
    assert "打印比例 100%" in svg
    assert "startouch" not in script_path.read_text(encoding="utf-8").lower()
