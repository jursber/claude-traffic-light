"""VibeLight 协议编解码自检。"""
from pathlib import Path
import sys

_ROOT = Path(__file__).resolve().parents[1]
_SRC = _ROOT / "src"
sys.path.insert(0, str(_SRC))

from claude_tl.vibelight.protocol import (
    CMD_SET_BREATH_CURVE,
    CURVE_SAMPLES_MAX,
    CURVE_SAMPLES_MIN,
    MODE_BREATH,
    MODE_SOLID,
    MASK_G,
    build_breath_curve_frame,
    build_set_lighting_frame,
    crc8,
    parse_breath_curve_frame,
    parse_frame,
)


def test_crc8_stable():
    b = bytes([1, 2, 3, 4, 5, 6, 7, 8, 9])
    assert crc8(b) == crc8(b)


def test_roundtrip():
    f = build_set_lighting_frame(MODE_SOLID, MASK_G, 1200, 100, 0, 0)
    assert len(f) == 12
    p = parse_frame(f)
    assert p is not None
    mode, mask, per, dg, dy, dr = p
    assert mode == MODE_SOLID
    assert mask == MASK_G
    assert per == 1200
    assert dg == 100 and dy == 0 and dr == 0


def test_period_clamp():
    f = build_set_lighting_frame(MODE_BREATH, 7, 10, 5, 5, 5)
    p = parse_frame(f)
    assert p is not None
    assert p[2] >= 50


def test_breath_curve_roundtrip():
    pts = tuple(20 + i * 7 for i in range(16))
    f = build_breath_curve_frame(MASK_G | 2, 3000, 200, 100, 0, pts)
    assert len(f) == 12 + 16
    assert f[3] == CMD_SET_BREATH_CURVE
    p = parse_breath_curve_frame(f)
    assert p is not None
    mask, period, dg, dy, dr, n, out = p
    assert mask == (MASK_G | 2)
    assert period == 3000
    assert dg == 200 and dy == 100 and dr == 0
    assert n == 16
    assert out == pts


def test_breath_curve_length_bounds():
    try:
        build_breath_curve_frame(1, 1000, 0, 0, 0, [0] * (CURVE_SAMPLES_MIN - 1))
    except ValueError:
        pass
    else:
        raise AssertionError("expected ValueError")
    try:
        build_breath_curve_frame(1, 1000, 0, 0, 0, [0] * (CURVE_SAMPLES_MAX + 1))
    except ValueError:
        pass
    else:
        raise AssertionError("expected ValueError")
