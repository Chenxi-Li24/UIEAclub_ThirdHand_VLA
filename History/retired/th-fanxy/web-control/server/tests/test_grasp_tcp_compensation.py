import math

import pytest

from grasp_tcp_compensation import parse_offset_m, tcp_position_to_flange


def test_identity_orientation_subtracts_tool_z_offset():
    flange = tcp_position_to_flange(
        [0.4, 0.2, 0.1],
        [0.0, 0.0, 0.0],
        [0.0, 0.0, 0.155],
    )
    assert flange == pytest.approx([0.4, 0.2, -0.055])


def test_pitch_rotates_tool_z_offset_into_base_x():
    flange = tcp_position_to_flange(
        [0.4, 0.2, 0.1],
        [0.0, math.pi / 2.0, 0.0],
        [0.0, 0.0, 0.155],
    )
    assert flange == pytest.approx([0.245, 0.2, 0.1], abs=1e-12)


def test_parser_accepts_configured_offset():
    assert parse_offset_m("0, 0, 0.155") == (0.0, 0.0, 0.155)


@pytest.mark.parametrize(
    "raw",
    ["0,0", "0,0,0,0", "0,nope,0", "0,nan,0", "0,inf,0"],
)
def test_parser_rejects_invalid_offset(raw):
    with pytest.raises(ValueError):
        parse_offset_m(raw)
