"""
Agent 切换脚本 - 在 Claude Code 和 OpenAI Codex 之间切换

用法：
  python switch_agent.py claude   # 切换到 Claude Code
  python switch_agent.py codex    # 切换到 OpenAI Codex
  python switch_agent.py status   # 查看当前状态
"""

import os
import sys
import json

from claude_tl._paths import active_agent_path, repo_root

CONFIG_FILE = str(active_agent_path())
CC_HOOKS_FILE = os.path.join(os.path.expanduser("~"), ".claude", "settings.json")
CODEX_HOOKS_FILE = os.path.join(os.path.expanduser("~"), ".codex", "hooks.json")


def hook_roots_normalized():
    """用于识别「是否为本项目 hook」的路径片段集合。"""
    roots = {str(repo_root()).replace("\\", "/")}
    env = os.environ.get("CC_TL_REPO_ROOT")
    if env:
        roots.add(env.replace("\\", "/").rstrip("/"))
    return roots


def hook_command(script: str, state: str) -> str:
    """
    生成红绿灯 hook 命令：调用仓库根目录下的启动器 .py（薄封装），
    以便在未 pip install 时也能通过 PYTHONPATH=src 的根 shim 工作。
    """
    root = os.environ.get("CC_TL_REPO_ROOT", str(repo_root()))
    script_path = os.path.join(root, script).replace("\\", "/")
    base = f'python "{script_path}"'
    return f"{base} {state}" if state else base


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
    """判断一个 hook 是否属于本红绿灯项目（含旧版绝对路径与 V3 根路径）。"""
    if not isinstance(hook, dict):
        return False
    command = str(hook.get("command", "")).replace("\\", "/")
    if "-m claude_tl" in command:
        return True
    for r in hook_roots_normalized():
        if r and r in command:
            return True
    return any(
        name in command
        for name in (
            "set_state_unified.py",
            "set_state.py",
            "set_alert_and_defer.py",
            "start_daemon_unified.py",
            "start_daemon.py",
        )
    )


def load_config():
    """加载配置文件"""
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {"active": "claude", "agents": {}}


def save_config(config):
    """保存配置文件"""
    os.makedirs(os.path.dirname(CONFIG_FILE) or ".", exist_ok=True)
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
            hook_group(hook_command("set_state_unified.py", "prompt")),
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
            hook_group(hook_command("set_state_unified.py", "prompt")),
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
