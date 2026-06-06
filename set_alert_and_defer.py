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

# 添加项目目录到路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import COMMANDS, STATE_DIR


def set_state(state: str, session_id: str = "") -> bool:
    """写入状态文件。"""
    if state not in COMMANDS:
        return False
    os.makedirs(STATE_DIR, exist_ok=True)
    state_file = os.path.join(STATE_DIR, session_id or "_global_alert")
    try:
        data = json.dumps({"state": state, "ts": time.time()})
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
            session_id = data.get("session_id", "")
    except (json.JSONDecodeError, EOFError, OSError):
        pass

    # 设置 alert 状态
    set_state("alert", session_id)

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
