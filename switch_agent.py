"""
Agent 切换脚本 - 在 Claude Code 和 OpenAI Codex 之间切换

用法：
  python switch_agent.py claude   # 切换到 Claude Code
  python switch_agent.py codex    # 切换到 OpenAI Codex
  python switch_agent.py status   # 查看当前状态
"""

import sys
import os
import json

# 添加项目目录到路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "active_agent.json")
CC_HOOKS_FILE = os.path.join(os.path.expanduser("~"), ".claude", "settings.json")
CODEX_HOOKS_FILE = os.path.join(os.path.expanduser("~"), ".codex", "hooks.json")
TRAFFIC_LIGHT_ROOT = "C:/Users/Administrator/.claude/traffic_light"


def load_config():
    """加载配置文件"""
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {"active": "claude", "agents": {}}


def save_config(config):
    """保存配置文件"""
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)


def load_json_file(path):
    """读取 JSON 配置文件，文件不存在或损坏时返回空配置。"""
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}


def save_json_file(path, data):
    """写入 JSON 配置文件。"""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def hook_command(script, state):
    """生成红绿灯 hook 命令。"""
    command = f"python {TRAFFIC_LIGHT_ROOT}/{script}"
    return f"{command} {state}" if state else command


def command_hook(command, timeout=5):
    """生成 command hook 配置。"""
    return {
        "type": "command",
        "command": command,
        "shell": "powershell",
        "timeout": timeout,
    }


def hook_group(command, matcher="", timeout=5):
    """生成单个 matcher 的 hook 分组。"""
    return {
        "matcher": matcher,
        "hooks": [command_hook(command, timeout)],
    }


def is_traffic_light_hook(hook):
    """判断一个 hook 是否属于本红绿灯项目。"""
    if not isinstance(hook, dict):
        return False
    command = str(hook.get("command", "")).replace("\\", "/")
    return TRAFFIC_LIGHT_ROOT in command


def remove_traffic_light_hooks(config):
    """只移除红绿灯自己的 hooks，保留用户已有的其它 hooks。"""
    hooks = config.get("hooks")
    if not isinstance(hooks, dict):
        return

    for event_name in list(hooks.keys()):
        groups = hooks.get(event_name)
        if not isinstance(groups, list):
            continue

        new_groups = []
        for group in groups:
            if not isinstance(group, dict):
                new_groups.append(group)
                continue

            hook_items = group.get("hooks")
            if not isinstance(hook_items, list):
                new_groups.append(group)
                continue

            kept_hooks = [hook for hook in hook_items if not is_traffic_light_hook(hook)]
            if kept_hooks:
                new_group = dict(group)
                new_group["hooks"] = kept_hooks
                new_groups.append(new_group)

        if new_groups:
            hooks[event_name] = new_groups
        else:
            del hooks[event_name]

    if not hooks:
        config.pop("hooks", None)


def add_hook_groups(config, hook_groups):
    """追加红绿灯 hooks。调用前会先清理旧的红绿灯 hooks。"""
    remove_traffic_light_hooks(config)
    hooks = config.setdefault("hooks", {})
    for event_name, groups in hook_groups.items():
        hooks.setdefault(event_name, []).extend(groups)


def claude_hook_groups():
    """Claude Code 的红绿灯 hooks。"""
    return {
        "SessionStart": [
            hook_group(hook_command("start_daemon_unified.py", ""), timeout=10),
        ],
        "UserPromptSubmit": [
            hook_group(hook_command("set_state_unified.py", "thinking")),
        ],
        "PreToolUse": [
            hook_group(hook_command("set_state_unified.py", "auto")),
        ],
        "PostToolBatch": [
            hook_group(hook_command("set_state_unified.py", "thinking")),
        ],
        "Stop": [
            hook_group(hook_command("set_state_unified.py", "idle")),
        ],
        "PermissionRequest": [
            hook_group(hook_command("set_alert_and_defer.py", "")),
        ],
        "Notification": [
            hook_group(hook_command("set_state_unified.py", "alert"), matcher="permission_prompt"),
        ],
        "StopFailure": [
            hook_group(hook_command("set_state_unified.py", "alert")),
        ],
        "SessionEnd": [
            hook_group(hook_command("set_state_unified.py", "off")),
        ],
    }


def codex_hook_groups():
    """Codex 的红绿灯 hooks。"""
    return {
        "UserPromptSubmit": [
            hook_group(hook_command("set_state_unified.py", "thinking")),
        ],
        "PreToolUse": [
            hook_group(hook_command("set_state_unified.py", "auto")),
        ],
        "PostToolUse": [
            hook_group(hook_command("set_state_unified.py", "thinking")),
        ],
        "Stop": [
            hook_group(hook_command("set_state_unified.py", "idle")),
        ],
        "SessionEnd": [
            hook_group(hook_command("set_state_unified.py", "off")),
        ],
    }


def set_claude_hooks(enable):
    """启用或禁用 Claude Code 的 traffic light hooks。"""
    config = load_json_file(CC_HOOKS_FILE)
    if enable:
        add_hook_groups(config, claude_hook_groups())
    else:
        remove_traffic_light_hooks(config)
    save_json_file(CC_HOOKS_FILE, config)


def set_codex_hooks(enable):
    """启用或禁用 Codex 的 traffic light hooks。"""
    config = load_json_file(CODEX_HOOKS_FILE)
    if enable:
        add_hook_groups(config, codex_hook_groups())
    else:
        remove_traffic_light_hooks(config)
    save_json_file(CODEX_HOOKS_FILE, config)


def switch_agent(agent):
    """切换到指定的 agent。"""
    config = load_config()

    if agent not in ["claude", "codex"]:
        print(f"无效的 agent: {agent}，支持的值: claude, codex")
        return False

    current = config.get("active", "claude")
    if current == "claude":
        set_claude_hooks(False)
    elif current == "codex":
        set_codex_hooks(False)

    if agent == "claude":
        set_claude_hooks(True)
    elif agent == "codex":
        set_codex_hooks(True)

    config["active"] = agent
    save_config(config)

    print(f"已切换到 {agent}")
    return True


def show_status():
    """显示当前状态。"""
    config = load_config()
    active = config.get("active", "claude")
    agents = config.get("agents", {})

    print(f"当前激活的 agent: {active}")
    print("Agent 配置:")
    for name, agent_config in agents.items():
        status = "ACTIVE 激活" if name == active else "  未激活"
        print(f"  {status} {name}: {agent_config.get('name', name)}")


def main():
    if len(sys.argv) < 2:
        print("用法:")
        print("  python switch_agent.py claude   # 切换到 Claude Code")
        print("  python switch_agent.py codex    # 切换到 OpenAI Codex")
        print("  python switch_agent.py status   # 查看当前状态")
        sys.exit(1)

    action = sys.argv[1]

    if action == "status":
        show_status()
    elif action in ["claude", "codex"]:
        switch_agent(action)
    else:
        print(f"无效的操作: {action}")
        sys.exit(1)


if __name__ == "__main__":
    main()
