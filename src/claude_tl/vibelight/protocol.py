"""
VibeLight 协议 v1 — 与固件 docs/VIBELIGHT_PROTOCOL.md 字节级一致。
"""

from __future__ import annotations

MAGIC = bytes((0xA5, 0x5A))
FRAME_LEN = 12
PROTO_VER = 1
CMD_SET_LIGHTING = 1
CMD_SET_BREATH_CURVE = 2

MODE_OFF = 0
MODE_SOLID = 1
MODE_SYNC_BLINK = 2
MODE_BREATH = 3
MODE_BREATH_CURVE = 4

CURVE_SAMPLES_MIN = 8
CURVE_SAMPLES_MAX = 32

MASK_G = 1
MASK_Y = 2
MASK_R = 4

PERIOD_MIN_MS = 50
PERIOD_MAX_MS = 60000


def crc8(data: bytes) -> int:
    """CRC-8/ATM：多项式 0x07，初值 0，与固件一致。"""
    crc = 0
    for b in data:
        crc ^= b & 0xFF
        for _ in range(8):
            if crc & 0x80:
                crc = ((crc << 1) ^ 0x07) & 0xFF
            else:
                crc = (crc << 1) & 0xFF
    return crc


def build_set_lighting_frame(
    mode: int,
    mask: int,
    period_ms: int,
    duty_g: int,
    duty_y: int,
    duty_r: int,
) -> bytes:
    """
    构造 12 字节 SET_LIGHTING 帧；参数在客户端先做钳位，固件侧仍会再钳位。
    """
    period_ms = max(PERIOD_MIN_MS, min(PERIOD_MAX_MS, int(period_ms)))
    duty_g = max(0, min(255, int(duty_g)))
    duty_y = max(0, min(255, int(duty_y)))
    duty_r = max(0, min(255, int(duty_r)))
    mode = max(0, min(255, int(mode)))
    mask = max(0, min(7, int(mask)))

    body = bytes(
        (
            PROTO_VER,
            CMD_SET_LIGHTING,
            mode,
            mask,
            period_ms & 0xFF,
            (period_ms >> 8) & 0xFF,
            duty_g,
            duty_y,
            duty_r,
        )
    )
    c = crc8(body)
    return MAGIC + body + bytes((c,))


def parse_frame(frame: bytes) -> tuple[int, int, int, int, int, int] | None:
    """校验并解析 SET_LIGHTING；失败返回 None。"""
    if len(frame) != FRAME_LEN or frame[0:2] != MAGIC:
        return None
    if frame[2] != PROTO_VER or frame[3] != CMD_SET_LIGHTING:
        return None
    body = frame[2:11]
    if crc8(body) != frame[11]:
        return None
    mode, mask, p0, p1, dg, dy, dr = frame[4], frame[5], frame[6], frame[7], frame[8], frame[9], frame[10]
    period = p0 | (p1 << 8)
    return (mode, mask, period, dg, dy, dr)


def build_breath_curve_frame(
    mask: int,
    period_ms: int,
    duty_g: int,
    duty_y: int,
    duty_r: int,
    samples: list[int] | tuple[int, ...] | bytes,
) -> bytes:
    """
    构造可变长度「自定义呼吸曲线」帧：魔数 + ver + cmd=2 + period + mask + n + duty*3 + n 字节包络 + CRC8。
    samples 为视觉亮度 0～255，等分一个周期；固件在相邻点间线性插值并首尾循环衔接。
    """
    if isinstance(samples, bytes):
        raw = list(samples)
    else:
        raw = [int(x) for x in samples]
    n = len(raw)
    if n < CURVE_SAMPLES_MIN or n > CURVE_SAMPLES_MAX:
        raise ValueError(f"samples length must be in [{CURVE_SAMPLES_MIN}, {CURVE_SAMPLES_MAX}], got {n}")

    period_ms = max(PERIOD_MIN_MS, min(PERIOD_MAX_MS, int(period_ms)))
    duty_g = max(0, min(255, int(duty_g)))
    duty_y = max(0, min(255, int(duty_y)))
    duty_r = max(0, min(255, int(duty_r)))
    mask = max(0, min(7, int(mask)))
    for i in range(n):
        raw[i] = max(0, min(255, raw[i]))

    body = bytes(
        (
            PROTO_VER,
            CMD_SET_BREATH_CURVE,
            period_ms & 0xFF,
            (period_ms >> 8) & 0xFF,
            mask,
            n,
            duty_g,
            duty_y,
            duty_r,
        )
    ) + bytes(raw)
    c = crc8(body)
    return MAGIC + body + bytes((c,))


def parse_breath_curve_frame(frame: bytes) -> tuple[int, int, int, int, int, int, tuple[int, ...]] | None:
    """解析 CMD_SET_BREATH_CURVE；失败返回 None。"""
    if len(frame) < 20 or frame[0:2] != MAGIC:
        return None
    if frame[2] != PROTO_VER or frame[3] != CMD_SET_BREATH_CURVE:
        return None
    n = frame[7]
    if n < CURVE_SAMPLES_MIN or n > CURVE_SAMPLES_MAX:
        return None
    if len(frame) != 12 + n:
        return None
    body = frame[2 : 11 + n]
    if crc8(body) != frame[11 + n]:
        return None
    mask = frame[6]
    p0, p1 = frame[4], frame[5]
    period = p0 | (p1 << 8)
    dg, dy, dr = frame[8], frame[9], frame[10]
    pts = tuple(int(b) for b in frame[11 : 11 + n])
    return (mask, period, dg, dy, dr, n, pts)
