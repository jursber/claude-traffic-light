"""
统一状态设置脚本 - 支持 Claude Code、OpenAI Codex 与 Cursor

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

from claude_tl._paths import active_agent_path
from claude_tl.config import COMMANDS

# ============================================================
# 配置文件路径
# ============================================================
CONFIG_FILE = str(active_agent_path())

# 需要显示"红灯闪烁"的工具列表
ALERT_TOOLS = {"AskUserQuestion", "question"}
STDIN_TIMEOUT = 0.2
LAST_SESSION_FILE = "_last_session"


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


def is_normal_session_id(session_id: str) -> bool:
    """Return True for real session files, excluding internal metadata."""
    return bool(session_id) and not session_id.startswith("_") and session_id == os.path.basename(session_id)


def read_last_session_id() -> str:
    """Read the most recent real session id."""
    path = os.path.join(get_state_dir(), LAST_SESSION_FILE)
    try:
        with open(path, "r", encoding="utf-8") as f:
            session_id = f.read().strip()
    except OSError:
        return ""
    return session_id if is_normal_session_id(session_id) else ""


def write_last_session_id(session_id: str) -> None:
    """Remember the latest real session for idle hooks that omit session_id."""
    if not is_normal_session_id(session_id):
        return

    state_dir = get_state_dir()
    os.makedirs(state_dir, exist_ok=True)
    path = os.path.join(state_dir, LAST_SESSION_FILE)
    tmp = path + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(session_id)
        os.replace(tmp, path)
    except OSError:
        pass


def set_state(state: str, session_id: str = "default", light: dict | None = None) -> bool:
    """把状态写到指定 session 的状态文件。

    light 为 None 时只写 {state, ts}（daemon 用该状态的默认灯效）；
    携带 {mode, mask, priority} 时一并写入，daemon 直接据此发扩展帧——
    这正是「三标签页里某个 hook 单独配的灯效」生效的通道。
    """
    if state not in COMMANDS:
        return False
    if not session_id or session_id != os.path.basename(session_id) or "\\" in session_id or "/" in session_id:
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
        write_last_session_id(session_id)
        return True
    except OSError:
        return False


def lookup_event_light(event_name: str) -> dict | None:
    """按 (当前 active agent, event) 在 tl_hook_light_gui.json 里查这个 hook 的灯效。

    返回 {mode, mask, priority}（effect 名 + 颜色掩码 + 优先级）；
    该 hook 未配灯（effect=none 或未选色）或查不到时返回 None → daemon 用默认灯效。
    """
    if not event_name:
        return None
    try:
        from claude_tl import light_effects as le

        active = load_config().get("active", "claude")
        doc = le.load_gui_doc()
        row = le.event_light_row(doc, active, event_name)
        if not row:
            return None
        effect = str(row.get("effect", "none")).lower()
        mask = int(row.get("mask", 0) or 0)
        if effect in ("", "none") or mask <= 0:
            return None
        return {"mode": effect, "mask": mask, "priority": int(row.get("priority", 12) or 12)}
    except Exception:
        return None


def read_stdin_with_timeout(timeout: float = STDIN_TIMEOUT) -> str:
    """读取 hook JSON；没有输入时快速返回，避免 hook 进程挂住。"""
    result = {"raw": ""}

    def reader():
        try:
            stdin = sys.stdin
            # 打包成 windowed 程序时 sys.stdin 可能为 None；正常 console/hook 管道下有效
            result["raw"] = stdin.read() if stdin is not None else ""
        except (EOFError, OSError, ValueError):
            result["raw"] = ""

    thread = threading.Thread(target=reader, daemon=True)
    thread.start()
    thread.join(timeout)
    return result["raw"] if not thread.is_alive() else ""


def has_prompt_text(data: dict) -> bool:
    """Return True when hook input contains a non-empty user prompt."""
    for key in ("prompt", "user_prompt", "message", "text"):
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            return True
        if isinstance(value, dict):
            content = value.get("content")
            if isinstance(content, str) and content.strip():
                return True
    return False


def main():
    if len(sys.argv) < 2:
        print(f"用法: {sys.argv[0]} <状态名|auto>", file=sys.stderr)
        sys.exit(1)

    state = sys.argv[1]

    # 可选 --event <事件名>：switch_agent 写 hooks 时带上，用于按 (agent, event) 查 per-hook 灯效
    event_name = ""
    rest = sys.argv[2:]
    i = 0
    while i < len(rest):
        if rest[i] == "--event" and i + 1 < len(rest):
            event_name = rest[i + 1]
            i += 2
            continue
        i += 1

    # 从 stdin 读取 hook 传来的 JSON
    session_id = ""
    tool_name = ""
    data = {}
    try:
        raw = read_stdin_with_timeout().strip()
        json_start = raw.find("{")
        if json_start > 0:
            raw = raw[json_start:]
        if raw:
            data = json.loads(raw)
            # Cursor：通用字段为 conversation_id；Claude/Codex 常用 session_id
            session_id = (data.get("session_id") or data.get("conversation_id") or "").strip()
            tool_name = data.get("tool_name", "")
    except (json.JSONDecodeError, EOFError, OSError):
        pass

    if state == "prompt":
        if has_prompt_text(data):
            state = "thinking"
        else:
            sys.exit(0)

    # 没有 session_id 的情况（例如 Cursor 的 hook 不带 conversation_id）：
    #   - off：写全局熄灯标记 _global_off
    #   - 其它(idle/thinking/working/...)：用上次真实会话名兜底；没有则用稳定合成名 _anon。
    # 之前这里对非 off/idle 直接 sys.exit(0)，导致 Cursor 下 thinking/working 永远不写、
    # 只有 idle(红灯)能亮。改为统一兜底后，黄/绿也能正常点亮。
    # _anon 以下划线开头，不会被 write_last_session_id 记成"上次会话"，也就不会污染兜底链。
    if not session_id:
        if state == "off":
            session_id = "_global_off"
        else:
            session_id = read_last_session_id() or "_anon"

    # auto 模式：根据 tool_name 自动决定状态
    if state == "auto":
        if tool_name in ALERT_TOOLS:
            state = "alert"
        else:
            state = "working"

    # per-hook 灯效：把这个 event 在 GUI 里配的「模式+颜色+优先级」一并写入状态文件
    light = lookup_event_light(event_name)
    sys.exit(0 if set_state(state, session_id, light) else 1)


if __name__ == "__main__":
    main()
