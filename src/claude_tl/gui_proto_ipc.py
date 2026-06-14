"""
GUI → 统一守护进程：通过 %TEMP% 下一键 JSON 提交 v1 原始帧（hex），由 daemon 独占串口/BLE 写出。

与「测试模式」配合：GUI 不直接打开 COM，避免与 daemon 抢端口。
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path


def gui_proto_request_path() -> str:
    return str(Path(os.environ.get("LOCALAPPDATA", "")) / "Temp" / "cc_tl_gui_proto.json")


def submit_gui_proto_hex(hex_no_space: str) -> None:
    """写入请求文件；守护进程读取后发送并删除。"""
    p = gui_proto_request_path()
    Path(p).parent.mkdir(parents=True, exist_ok=True)
    payload = {"hex": hex_no_space.strip(), "ts": time.time()}
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False)
    os.replace(tmp, p)
