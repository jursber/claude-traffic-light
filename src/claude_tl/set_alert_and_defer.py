"""
PermissionRequest hook 专用脚本

功能：
  1. 设置 alert 状态（红灯闪烁）
  2. 返回 defer 决策，让 CC 继续显示权限弹窗

用法：被 PermissionRequest hook 调用，不直接使用
"""

import sys
import os
import json
import time

from claude_tl.config import COMMANDS
from claude_tl.set_state_unified import get_state_dir, lookup_event_light


def set_state(state: str, session_id: str = "", light: dict | None = None) -> bool:
    """写入状态文件。没有 session_id 时不写入（避免残留文件）。"""
    if state not in COMMANDS:
        return False
    if not session_id:
        return False  # 没有 session_id 就不写，防止 _global_alert 残留
    if session_id != os.path.basename(session_id) or "\\" in session_id or "/" in session_id:
        return False
    state_dir = get_state_dir()
    os.makedirs(state_dir, exist_ok=True)
    state_file = os.path.join(state_dir, session_id)
    try:
        payload = {"state": state, "ts": time.time()}
        if isinstance(light, dict) and light:
            payload.update(light)
        data = json.dumps(payload)
        tmp = state_file + ".tmp"
        with open(tmp, "w") as f:
            f.write(data)
        os.replace(tmp, state_file)
        return True
    except OSError:
        return False


def main():
    # 读取 stdin JSON（CC 传来的事件信息）
    session_id = ""
    try:
        raw = sys.stdin.read().strip()
        if raw:
            data = json.loads(raw)
            session_id = (data.get("session_id") or data.get("conversation_id") or "").strip()
    except (json.JSONDecodeError, EOFError, OSError):
        pass

    # 设置 alert 状态
    set_state("alert", session_id, lookup_event_light("PermissionRequest"))

    # 返回 defer 决策，让 CC 继续显示权限弹窗
    # 这样我们只是观察事件，不改变权限流程
    result = {
        "hookSpecificOutput": {
            "permissionDecision": "defer"
        }
    }
    print(json.dumps(result))


if __name__ == "__main__":
    main()
