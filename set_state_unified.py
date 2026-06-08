"""
统一状态设置脚本 - 支持 Claude Code 和 OpenAI Codex

工作原理：
  1. 根据 active_agent.json 配置确定当前激活的 agent
  2. 读取对应 agent 的状态目录
  3. 写入状态文件，守护进程统一读取

用法：
  python set_state_unified.py thinking   # 设置 thinking 状态
  python set_state_unified.py auto       # 自动模式（根据 tool_name 决定）
"""

import sys
import os
import json
import time
import threading

# 添加项目目录到路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import COMMANDS, STATE_DIR

# ============================================================
# 配置文件路径
# ============================================================
CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "active_agent.json")

# 需要显示"红灯闪烁"的工具列表
ALERT_TOOLS = {"AskUserQuestion", "question"}
STDIN_TIMEOUT = 0.2


def load_config():
    """加载 active_agent.json 配置"""
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {"active": "claude"}


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


def set_state(state: str, session_id: str = "default") -> bool:
    """把状态写到指定 session 的状态文件"""
    if state not in COMMANDS:
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
    except OSError:
        return False


def read_stdin_with_timeout(timeout: float = STDIN_TIMEOUT) -> str:
    """读取 hook JSON；没有输入时快速返回，避免 hook 进程挂住。"""
    result = {"raw": ""}

    def reader():
        try:
            result["raw"] = sys.stdin.read()
        except (EOFError, OSError):
            result["raw"] = ""

    thread = threading.Thread(target=reader, daemon=True)
    thread.start()
    thread.join(timeout)
    return result["raw"] if not thread.is_alive() else ""


def main():
    if len(sys.argv) < 2:
        print(f"用法: {sys.argv[0]} <状态名|auto>", file=sys.stderr)
        sys.exit(1)

    state = sys.argv[1]

    # 从 stdin 读取 hook 传来的 JSON
    session_id = ""
    tool_name = ""
    try:
        raw = read_stdin_with_timeout().strip()
        json_start = raw.find("{")
        if json_start > 0:
            raw = raw[json_start:]
        if raw:
            data = json.loads(raw)
            session_id = data.get("session_id", "")
            tool_name = data.get("tool_name", "")
    except (json.JSONDecodeError, EOFError, OSError):
        pass

    # 如果没有 session_id，非 off 状态直接跳过，避免残留 default 状态抢占显示
    if not session_id:
        if state == "off":
            session_id = "_global_off"
        else:
            sys.exit(0)

    # auto 模式：根据 tool_name 自动决定状态
    if state == "auto":
        if tool_name in ALERT_TOOLS:
            state = "alert"
        else:
            state = "working"

    sys.exit(0 if set_state(state, session_id) else 1)


if __name__ == "__main__":
    main()
