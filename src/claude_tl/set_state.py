"""
状态设置脚本 - 被 CC hooks 调用的入口

工作原理：
  1. CC 触发 hook 事件（比如用户发消息、调用工具等）
  2. hook 通过 stdin 传入 JSON（包含 session_id 和 tool_name）
  3. 本脚本读取 JSON，把状态写到 {STATE_DIR}/{session_id} 文件
  4. 守护进程检测到文件变化，通过串口发送指令给 ESP32C3

用法：
  # 普通模式：直接指定状态
  echo '{"session_id":"abc123"}' | python set_state.py idle

  # 自动模式：根据 tool_name 自动决定状态
  echo '{"session_id":"abc123","tool_name":"AskUserQuestion"}' | python set_state.py auto
"""

import sys
import os
import json
import time

from claude_tl.config import COMMANDS, STATE_DIR

DEPRECATED_NOTICE = (
    "警告：set_state.py 是 V1/V2 经典入口，V3 推荐使用 set_state_unified.py "
    "或 VibeLight.exe set-state-unified。"
)


def _warn_deprecated() -> None:
    print(DEPRECATED_NOTICE, file=sys.stderr)

# ============================================================
# 需要显示"红灯闪烁"的工具列表
# ============================================================
# AskUserQuestion 是 CC 的交互式提问工具，用户需要操作
# 所以它应该触发 alert 状态（红灯闪烁），而不是 working（绿灯常亮）
ALERT_TOOLS = {"AskUserQuestion"}


def set_state(state: str, session_id: str = "default") -> bool:
    """
    把状态写到指定 session 的状态文件。

    文件格式：JSON，包含 state（状态名）和 timestamp（时间戳）
    时间戳用于心跳超时检测：如果活跃状态超过 60 秒没更新，
    守护进程会自动降级为 idle，防止崩溃后灯永远亮着。

    使用"写临时文件再重命名"的方式，保证原子性：
    防止守护进程读到写了一半的文件。

    Args:
        state: 状态名称（必须在 COMMANDS 中定义）
        session_id: 会话 ID（每个 CC 终端唯一）

    Returns:
        True 写入成功，False 状态名无效
    """
    if state not in COMMANDS:
        return False
    os.makedirs(STATE_DIR, exist_ok=True)
    state_file = os.path.join(STATE_DIR, session_id)
    try:
        # 写入 JSON 格式：状态名 + 时间戳
        data = json.dumps({"state": state, "ts": time.time()})
        tmp = state_file + ".tmp"
        with open(tmp, "w") as f:
            f.write(data)
        os.replace(tmp, state_file)  # 原子替换，不会读到半写状态
        return True
    except OSError:
        return False


def main():
    _warn_deprecated()
    # 至少需要一个参数：状态名
    if len(sys.argv) < 2:
        print(f"用法: {sys.argv[0]} <状态名|auto>", file=sys.stderr)
        sys.exit(1)

    state = sys.argv[1]

    # ----------------------------------------------------------
    # 从 stdin 读取 CC hook 传来的 JSON
    # ----------------------------------------------------------
    # CC 每次触发 hook 时，会把事件信息以 JSON 格式传到 stdin
    # 包含 session_id（会话ID）、tool_name（工具名）等字段
    session_id = ""
    tool_name = ""
    try:
        raw = sys.stdin.read().strip()
        if raw:
            data = json.loads(raw)
            session_id = data.get("session_id", "")
            tool_name = data.get("tool_name", "")
    except (json.JSONDecodeError, EOFError, OSError):
        pass

    # 如果没有 session_id，说明 hook 没正确传递数据
    # 对于 off 状态（会话结束），写入一个通用文件让守护进程关灯
    # 其他状态跳过，防止写入无意义的 "default" 文件
    if not session_id:
        if state == "off":
            # 写入全局 off 文件，守护进程会读取并关灯
            session_id = "_global_off"
        else:
            sys.exit(0)

    # ----------------------------------------------------------
    # auto 模式：根据 tool_name 自动决定状态
    # ----------------------------------------------------------
    # PreToolUse hook 使用 auto 模式
    # 如果工具在 ALERT_TOOLS 中 → alert（红灯闪烁）
    # 其他工具 → working（绿灯常亮）
    if state == "auto":
        if tool_name in ALERT_TOOLS:
            state = "alert"
        else:
            state = "working"

    # 写入状态文件
    sys.exit(0 if set_state(state, session_id) else 1)


if __name__ == "__main__":
    main()
