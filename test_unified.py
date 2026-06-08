"""
统一架构测试脚本

测试 Claude Code 和 OpenAI Codex 的红绿灯系统是否正常工作
"""

import sys
import os
import json
import time

# 添加项目目录到路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import COMMANDS, STATE_DIR

# 配置文件
CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "active_agent.json")


def load_config():
    """加载配置文件"""
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {"active": "claude", "agents": {}}


def get_state_dir():
    """根据当前激活的 agent 获取状态目录"""
    config = load_config()
    active = config.get("active", "claude")
    agents = config.get("agents", {})

    if active in agents:
        state_dir_name = agents[active].get("state_dir", "cc_tl_states")
    else:
        state_dir_name = "cc_tl_states"

    return os.path.join(os.environ.get("LOCALAPPDATA", ""), "Temp", state_dir_name)


def set_state(state: str, session_id: str = "test_session") -> bool:
    """写入状态文件"""
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
        print(f"写入状态文件失败: {e}")
        return False


def test_states():
    """测试所有状态"""
    config = load_config()
    active = config.get("active", "claude")

    print(f"当前 agent: {active}")
    print(f"状态目录: {get_state_dir()}")
    print()

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
        if set_state(state):
            print(f"  OK 已写入状态文件")
        else:
            print(f"  FAIL 写入失败")
        time.sleep(2)

    # 清理测试文件
    state_dir = get_state_dir()
    test_file = os.path.join(state_dir, "test_session")
    if os.path.exists(test_file):
        os.remove(test_file)
        print("\n已清理测试文件")


def main():
    if len(sys.argv) < 2:
        print("用法:")
        print("  python test_unified.py test    # 测试所有状态")
        print("  python test_unified.py status  # 查看当前状态")
        sys.exit(1)

    action = sys.argv[1]

    if action == "test":
        test_states()
    elif action == "status":
        config = load_config()
        active = config.get("active", "claude")
        print(f"当前 agent: {active}")
        print(f"状态目录: {get_state_dir()}")
    else:
        print(f"无效的操作: {action}")
        sys.exit(1)


if __name__ == "__main__":
    main()
