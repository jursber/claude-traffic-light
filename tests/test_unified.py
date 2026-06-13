"""
统一架构手动测试（需 unified 守护进程）。

用法:
  python tests/test_unified.py test
  python tests/test_unified.py status
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_SRC = _ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from claude_tl._paths import active_agent_path
from claude_tl.config import COMMANDS

CONFIG_FILE = str(active_agent_path())


def load_config():
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {"active": "claude", "agents": {}}


def get_state_dir():
    config = load_config()
    active = config.get("active", "claude")
    agents = config.get("agents", {})
    if active in agents:
        state_dir_name = agents[active].get("state_dir", "cc_tl_states")
    else:
        state_dir_name = "cc_tl_states"
    return os.path.join(os.environ.get("LOCALAPPDATA", ""), "Temp", state_dir_name)


def set_state(state: str, session_id: str = "test_session") -> bool:
    if state not in COMMANDS:
        print(f"无效状态: {state}")
        return False
    state_dir = get_state_dir()
    os.makedirs(state_dir, exist_ok=True)
    state_file = os.path.join(state_dir, session_id)
    try:
        data = json.dumps({"state": state, "ts": time.time()})
        tmp = state_file + ".tmp"
        with open(tmp, "w") as f:
            f.write(data)
        os.replace(tmp, state_file)
        return True
    except OSError as e:
        print(f"写入失败: {e}")
        return False


def test_states():
    config = load_config()
    active = config.get("active", "claude")
    print(f"当前 agent: {active}")
    print(f"状态目录: {get_state_dir()}\n")
    states = [
        ("thinking", "黄灯闪烁"),
        ("working", "绿灯常亮"),
        ("model", "绿灯闪烁"),
        ("alert", "红灯闪烁"),
        ("idle", "红灯常亮"),
        ("off", "全灭"),
    ]
    for state, desc in states:
        print(f"测试 {state} ({desc})...")
        print("  OK" if set_state(state) else "  FAIL")
        time.sleep(2)
    test_file = os.path.join(get_state_dir(), "test_session")
    if os.path.exists(test_file):
        os.remove(test_file)
        print("\n已清理测试文件")


def main():
    if len(sys.argv) < 2:
        print("用法: python tests/test_unified.py test|status")
        sys.exit(1)
    action = sys.argv[1]
    if action == "test":
        test_states()
    elif action == "status":
        config = load_config()
        print(f"当前 agent: {config.get('active', 'claude')}")
        print(f"状态目录: {get_state_dir()}")
    else:
        sys.exit(1)


if __name__ == "__main__":
    main()
