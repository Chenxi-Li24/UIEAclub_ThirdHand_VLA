#!/usr/bin/env python3
"""Generate an exact-size A3 SVG for the configured Kalibr AprilGrid."""

from __future__ import annotations

import argparse
import os
import tempfile
from html import escape
from pathlib import Path

import cv2
import yaml

PAGE_WIDTH_MM = 297.0
PAGE_HEIGHT_MM = 420.0
MARKER_CELLS = 8


def _load_target(path: Path) -> dict[str, float | int]:
    try:
        payload = yaml.safe_load(path.resolve(strict=True).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        raise ValueError("AprilGrid target cannot be parsed") from exc
    expected = {"target_type", "tagCols", "tagRows", "tagSize", "tagSpacing"}
    if not isinstance(payload, dict) or set(payload) != expected:
        raise ValueError("AprilGrid target keys are invalid")
    if payload["target_type"] != "aprilgrid":
        raise ValueError("target_type must be aprilgrid")
    columns = payload["tagCols"]
    rows = payload["tagRows"]
    if any(isinstance(value, bool) or not isinstance(value, int) for value in (columns, rows)):
        raise ValueError("AprilGrid rows and columns must be integers")
    tag_size_m = float(payload["tagSize"])
    spacing_ratio = float(payload["tagSpacing"])
    if not 2 <= rows <= 20 or not 2 <= columns <= 20:
        raise ValueError("AprilGrid dimensions are unsupported")
    if not 0.005 <= tag_size_m <= 0.2 or not 0.0 <= spacing_ratio <= 1.0:
        raise ValueError("AprilGrid metric dimensions are invalid")
    return {
        "columns": columns,
        "rows": rows,
        "tag_size_m": tag_size_m,
        "spacing_ratio": spacing_ratio,
    }


def _marker_svg(marker_id: int, x_mm: float, y_mm: float, size_mm: float) -> str:
    dictionary = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_APRILTAG_36h11)
    marker = cv2.aruco.generateImageMarker(
        dictionary,
        marker_id,
        MARKER_CELLS,
        borderBits=1,
    )
    cell = size_mm / MARKER_CELLS
    rectangles = []
    for row in range(MARKER_CELLS):
        for column in range(MARKER_CELLS):
            if int(marker[row, column]) < 128:
                rectangles.append(
                    f'<rect x="{x_mm + column * cell:.6f}" '
                    f'y="{y_mm + row * cell:.6f}" width="{cell:.6f}" '
                    f'height="{cell:.6f}" fill="#000"/>'
                )
    return f'<g data-tag-id="{marker_id}">' + "".join(rectangles) + "</g>"


def _atomic_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def generate_target(target_path: Path | str, output_path: Path | str) -> dict[str, float | int]:
    target = _load_target(Path(target_path))
    columns = int(target["columns"])
    rows = int(target["rows"])
    tag_size_mm = float(target["tag_size_m"]) * 1000.0
    gap_mm = tag_size_mm * float(target["spacing_ratio"])
    grid_width = columns * tag_size_mm + (columns - 1) * gap_mm
    grid_height = rows * tag_size_mm + (rows - 1) * gap_mm
    if grid_width > PAGE_WIDTH_MM - 10.0 or grid_height > PAGE_HEIGHT_MM - 60.0:
        raise ValueError("AprilGrid does not fit the A3 page with measurement marks")
    origin_x = (PAGE_WIDTH_MM - grid_width) / 2.0
    origin_y = (PAGE_HEIGHT_MM - grid_height) / 2.0 - 10.0
    markers = []
    for row in range(rows):
        for column in range(columns):
            marker_id = row * columns + column
            x_mm = origin_x + column * (tag_size_mm + gap_mm)
            y_mm = origin_y + row * (tag_size_mm + gap_mm)
            markers.append(_marker_svg(marker_id, x_mm, y_mm, tag_size_mm))
    label_y = origin_y + grid_height + 28.0
    ruler_y = label_y + 12.0
    title = escape(
        f"AprilGrid {columns}x{rows} · tag36h11 · tag {tag_size_mm:.1f} mm · "
        f"gap {gap_mm:.1f} mm"
    )
    svg = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{PAGE_WIDTH_MM:g}mm" '
        f'height="{PAGE_HEIGHT_MM:g}mm" viewBox="0 0 {PAGE_WIDTH_MM:g} '
        f'{PAGE_HEIGHT_MM:g}">\n'
        '<rect width="100%" height="100%" fill="#fff"/>\n'
        + "\n".join(markers)
        + "\n"
        f'<text x="{PAGE_WIDTH_MM / 2:.3f}" y="{label_y:.3f}" text-anchor="middle" '
        f'font-family="sans-serif" font-size="4">{title}</text>\n'
        f'<text x="{PAGE_WIDTH_MM / 2:.3f}" y="{label_y + 6:.3f}" text-anchor="middle" '
        'font-family="sans-serif" font-size="4">打印比例 100% · 禁止适应页面 · 打印后实测</text>\n'
        f'<line x1="{(PAGE_WIDTH_MM - 100.0) / 2:.3f}" y1="{ruler_y:.3f}" '
        f'x2="{(PAGE_WIDTH_MM + 100.0) / 2:.3f}" y2="{ruler_y:.3f}" '
        'stroke="#000" stroke-width="0.4"/>\n'
        f'<line x1="{(PAGE_WIDTH_MM - 100.0) / 2:.3f}" y1="{ruler_y - 2:.3f}" '
        f'x2="{(PAGE_WIDTH_MM - 100.0) / 2:.3f}" y2="{ruler_y + 2:.3f}" '
        'stroke="#000" stroke-width="0.4"/>\n'
        f'<line x1="{(PAGE_WIDTH_MM + 100.0) / 2:.3f}" y1="{ruler_y - 2:.3f}" '
        f'x2="{(PAGE_WIDTH_MM + 100.0) / 2:.3f}" y2="{ruler_y + 2:.3f}" '
        'stroke="#000" stroke-width="0.4"/>\n'
        f'<text x="{PAGE_WIDTH_MM / 2:.3f}" y="{ruler_y + 6:.3f}" '
        'text-anchor="middle" font-family="sans-serif" font-size="4">100 mm 校验线</text>\n'
        "</svg>\n"
    )
    _atomic_text(Path(output_path), svg)
    return {
        "page_width_mm": PAGE_WIDTH_MM,
        "page_height_mm": PAGE_HEIGHT_MM,
        "rows": rows,
        "columns": columns,
        "tag_size_mm": tag_size_mm,
        "gap_mm": gap_mm,
        "grid_size_mm": grid_width,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--target",
        type=Path,
        default=Path("configs/vision/calibration/aprilgrid_6x6.yaml"),
    )
    parser.add_argument("--output", required=True, type=Path)
    arguments = parser.parse_args()
    metadata = generate_target(arguments.target, arguments.output)
    print(
        f"output={arguments.output} grid={metadata['grid_size_mm']:.1f}mm "
        f"tag={metadata['tag_size_mm']:.1f}mm gap={metadata['gap_mm']:.1f}mm"
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError) as error:
        raise SystemExit(f"AprilGrid generation rejected: {error}") from error
