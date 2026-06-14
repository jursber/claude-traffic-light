"""
状态 → 灯效（扩展帧）的「单一真相源」。

daemon 显示状态灯、GUI 配置「状态灯效」面板都从这里取默认值、做读写与转帧，
避免两边各写一套导致「保存了但 daemon 不认」。

配置存放在 config/tl_hook_light_gui.json 顶层的 "state_effects"：

    "state_effects": {
        "<state>": {
            "mode":      "off" | "solid" | "blink" | "breath",
            "mask":      0..7,          # 位：G=1, Y=2, R=4（可组合）
            "period_ms": int,           # 闪烁/呼吸周期；常亮时无意义
            "duty":      0..255         # 该状态选中颜色的亮度
        },
        ...
    }

只有 5 个「活动状态」可配：model / working / thinking / alert / idle。
off（会话结束/全灭）固定为全灭，不接受配置，保证「关灯永远能关」。
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from claude_tl._paths import repo_root
from claude_tl.vibelight.protocol import (
    MASK_G,
    MASK_R,
    MASK_Y,
    MODE_BREATH,
    MODE_OFF,
    MODE_SOLID,
    MODE_SYNC_BLINK,
    build_set_lighting_frame,
)

# GUI 模式名 ↔ 协议模式码
MODE_NAME_TO_CODE: dict[str, int] = {
    "off": MODE_OFF,
    "solid": MODE_SOLID,
    "blink": MODE_SYNC_BLINK,
    "breath": MODE_BREATH,
}
MODE_CODE_TO_NAME: dict[int, str] = {v: k for k, v in MODE_NAME_TO_CODE.items()}

# 默认灯效：与历史单字符 COMMANDS 行为对齐
#   model=绿闪 / working=绿常亮 / thinking=黄闪 / alert=红闪 / idle=红常亮
DEFAULT_STATE_EFFECTS: dict[str, dict] = {
    "model": {"mode": "blink", "mask": MASK_G, "period_ms": 800, "duty": 255},
    "working": {"mode": "solid", "mask": MASK_G, "period_ms": 1000, "duty": 255},
    "thinking": {"mode": "blink", "mask": MASK_Y, "period_ms": 800, "duty": 255},
    "alert": {"mode": "blink", "mask": MASK_R, "period_ms": 500, "duty": 255},
    "idle": {"mode": "solid", "mask": MASK_R, "period_ms": 1000, "duty": 255},
}

# GUI 展示顺序与中文标签（按优先级从高到低）
STATE_ORDER: tuple[str, ...] = ("alert", "thinking", "model", "working", "idle")
STATE_LABELS: dict[str, str] = {
    "alert": "alert · 需关注/出错/授权",
    "thinking": "thinking · 思考中",
    "model": "model · 等模型响应",
    "working": "working · 正在执行",
    "idle": "idle · 等你输入",
}

_ALLOWED_KEYS = ("mode", "mask", "period_ms", "duty")


def config_path() -> Path:
    """tl_hook_light_gui.json 的绝对路径（GUI 与 daemon 共用）。"""
    home = os.environ.get("CC_TL_HOME")
    base = Path(home).expanduser().resolve() if home else repo_root()
    return base / "config" / "tl_hook_light_gui.json"


def _sanitize_effect(state: str, raw: dict) -> dict:
    """把外部读入的单条灯效配置规整为合法字段，非法处回落默认。"""
    base = dict(DEFAULT_STATE_EFFECTS[state])
    if not isinstance(raw, dict):
        return base
    mode = str(raw.get("mode", base["mode"])).lower().strip()
    if mode in MODE_NAME_TO_CODE:
        base["mode"] = mode
    try:
        base["mask"] = max(0, min(7, int(raw.get("mask", base["mask"]))))
    except (TypeError, ValueError):
        pass
    try:
        base["period_ms"] = max(0, int(raw.get("period_ms", base["period_ms"])))
    except (TypeError, ValueError):
        pass
    try:
        base["duty"] = max(0, min(255, int(raw.get("duty", base["duty"]))))
    except (TypeError, ValueError):
        pass
    return base


def normalize_state_effects(raw: dict | None) -> dict[str, dict]:
    """以默认值为底，叠加用户配置中合法的 5 个活动状态。"""
    out = {k: dict(v) for k, v in DEFAULT_STATE_EFFECTS.items()}
    if isinstance(raw, dict):
        for state in DEFAULT_STATE_EFFECTS:
            if state in raw:
                out[state] = _sanitize_effect(state, raw[state])
    return out


def load_state_effects(path: str | os.PathLike | None = None) -> dict[str, dict]:
    """从配置文件读取并规整 state_effects；文件缺失/损坏时返回默认。"""
    p = Path(path) if path is not None else config_path()
    try:
        with open(p, "r", encoding="utf-8") as f:
            doc = json.load(f)
        raw = doc.get("state_effects")
    except (OSError, json.JSONDecodeError, AttributeError):
        raw = None
    return normalize_state_effects(raw)


def config_mtime(path: str | os.PathLike | None = None) -> float:
    """配置文件 mtime；不存在返回 0.0。用于热重载判定。"""
    p = Path(path) if path is not None else config_path()
    try:
        return os.path.getmtime(p)
    except OSError:
        return 0.0


def effect_to_frame(effect: dict) -> bytes:
    """把单条灯效配置转成 SET_LIGHTING 12 字节帧。"""
    mode = MODE_NAME_TO_CODE.get(str(effect.get("mode", "solid")).lower(), MODE_SOLID)
    mask = max(0, min(7, int(effect.get("mask", 0))))
    period = int(effect.get("period_ms", 1000)) or 1000
    duty = max(0, min(255, int(effect.get("duty", 255))))
    dg = duty if mask & MASK_G else 0
    dy = duty if mask & MASK_Y else 0
    dr = duty if mask & MASK_R else 0
    return build_set_lighting_frame(mode, mask, period, dg, dy, dr)


def off_frame() -> bytes:
    """全灭帧（会话结束/兜底关灯）。"""
    return build_set_lighting_frame(MODE_OFF, 0, 1000, 0, 0, 0)


def state_to_frame(state: str, effects: dict[str, dict]) -> bytes:
    """状态 → 待发送帧。未知状态与 off 一律全灭，保证「关灯永远能关」。"""
    if state == "off" or state not in effects:
        return off_frame()
    return effect_to_frame(effects[state])


# ============================================================
# V2：per-hook 灯效（三标签页 rows 直接驱动 daemon）
# ============================================================
# 灯效「单一真相源」改为三标签页的 per-agent rows：每个 hook 行配
# 「模式(effect) + 颜色(mask) + 优先级」；闪烁/呼吸周期与三色亮度是「基础设置」里的
# 全局值。set_state 触发时把命中行的灯效写进状态文件，daemon 直接据此发扩展帧。

# set_state 首参(wire_state) → 运行时实际显示的「状态组」。
# prompt 经 has_prompt_text 实际写 thinking；auto 经 tool_name 实际写 working/alert。
WIRE_TO_GROUP_STATE: dict[str, str] = {
    "prompt": "thinking",
    "auto": "working",
    "thinking": "thinking",
    "working": "working",
    "model": "working",
    "alert": "alert",
    "idle": "idle",
    "off": "off",
}

# GUI 三标签页分组展示顺序与中文标签（off 固定全灭、不在可配组内）。
GROUP_STATE_ORDER: tuple[str, ...] = ("alert", "thinking", "working", "idle")
GROUP_STATE_LABELS: dict[str, str] = {
    "alert": "告警 · 需关注 / 出错 / 授权",
    "thinking": "思考中 · 等模型 / 思考 / 压缩",
    "working": "正在执行 · 工具或子代理完成",
    "idle": "等待输入 · 本回合结束",
}


def group_state_for_wire(wire_state: str) -> str:
    """hook 的 wire_state → 它在 GUI 里默认归属的状态组。"""
    return WIRE_TO_GROUP_STATE.get(str(wire_state), "working")


def load_gui_doc(path: str | os.PathLike | None = None) -> dict:
    """读取整份 tl_hook_light_gui.json；缺失/损坏返回 {}。"""
    p = Path(path) if path is not None else config_path()
    try:
        with open(p, "r", encoding="utf-8") as f:
            doc = json.load(f)
        return doc if isinstance(doc, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def basic_light_params(doc: dict) -> dict:
    """从 doc.basic 取「全局」周期与三色亮度（闪烁/呼吸周期、绿黄红亮度）。"""
    b = doc.get("basic") if isinstance(doc, dict) else None
    b = b if isinstance(b, dict) else {}

    def _i(key: str, dflt: int) -> int:
        try:
            return int(b.get(key, dflt))
        except (TypeError, ValueError):
            return dflt

    return {
        "blink_period_ms": max(0, _i("blink_period_ms", 800)),
        "breath_period_ms": max(0, _i("breath_period_ms", 2000)),
        "duty_g": max(0, min(255, _i("duty_g", 255))),
        "duty_y": max(0, min(255, _i("duty_y", 255))),
        "duty_r": max(0, min(255, _i("duty_r", 255))),
    }


def event_light_row(doc: dict, agent: str, event: str) -> dict | None:
    """在 doc[agent].rows 里按 event 找该 hook 的灯效行；找不到返回 None。"""
    agent_cfg = doc.get(agent) if isinstance(doc, dict) else None
    rows = agent_cfg.get("rows") if isinstance(agent_cfg, dict) else None
    if not isinstance(rows, list):
        return None
    for r in rows:
        if isinstance(r, dict) and str(r.get("event")) == str(event):
            return r
    return None


def _period_for_mode(mode_name: str, basic: dict) -> int:
    if mode_name == "blink":
        return basic.get("blink_period_ms", 800) or 800
    if mode_name == "breath":
        return basic.get("breath_period_ms", 2000) or 2000
    return 1000


def frame_from_light(mode_name: str, mask: int, basic: dict) -> bytes:
    """模式名 + 颜色掩码 + 全局周期/亮度 → SET_LIGHTING 帧。"""
    name = str(mode_name).lower()
    mode = MODE_NAME_TO_CODE.get(name, MODE_SOLID)
    mask = max(0, min(7, int(mask)))
    if mode == MODE_OFF or mask == 0:
        return off_frame()
    period = _period_for_mode(name, basic)
    dg = basic.get("duty_g", 255) if mask & MASK_G else 0
    dy = basic.get("duty_y", 255) if mask & MASK_Y else 0
    dr = basic.get("duty_r", 255) if mask & MASK_R else 0
    return build_set_lighting_frame(mode, mask, period, dg, dy, dr)


def default_light_for_state(state: str) -> tuple[str, int]:
    """状态的默认（模式名, 掩码），用于状态文件未携带灯效时回退。"""
    eff = DEFAULT_STATE_EFFECTS.get(state)
    if not eff:
        return ("off", 0)
    return (str(eff["mode"]), int(eff["mask"]))


def frame_for_runtime(state: str, mode_name: str | None, mask: int | None, basic: dict) -> bytes:
    """daemon 用：当前最高优先级状态 → 帧。off 与缺省一律安全回退。"""
    if state == "off":
        return off_frame()
    if mode_name is None or mask is None:
        mode_name, mask = default_light_for_state(state)
    return frame_from_light(mode_name, mask, basic)
