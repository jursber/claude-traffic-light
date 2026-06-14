"""
Agent 切换脚本 - 在 Claude Code、OpenAI Codex、Cursor 之间切换

用法：
  python switch_agent.py claude   # 切换到 Claude Code
  python switch_agent.py codex    # 切换到 OpenAI Codex
  python switch_agent.py cursor   # 切换到 Cursor（~/.cursor/hooks.json）
  python switch_agent.py status   # 查看当前状态
"""

import json
import os
import sys

from claude_tl._paths import active_agent_path, repo_root
from claude_tl.hook_light_catalog import (
    iter_claude_wired_hook_groups,
    iter_codex_wired_hook_groups,
    iter_cursor_wired_hook_items,
)

CONFIG_FILE = str(active_agent_path())
CC_HOOKS_FILE = os.path.join(os.path.expanduser("~"), ".claude", "settings.json")
CODEX_HOOKS_FILE = os.path.join(os.path.expanduser("~"), ".codex", "hooks.json")
CURSOR_HOOKS_FILE = os.path.join(os.path.expanduser("~"), ".cursor", "hooks.json")


def _safe_print(msg: str) -> None:
    """
    pythonw / FreeConsole 后 sys.stdout 可能指向无效控制台句柄，后台线程里 print 会触发 WinError 6。
    GUI 通过线程调用 switch_agent 时必须避免裸 print。
    """
    try:
        out = getattr(sys, "stdout", None)
        if out is None:
            return
        out.write(msg + ("\n" if not msg.endswith("\n") else ""))
        out.flush()
    except (OSError, AttributeError, TypeError):
        pass


def hook_roots_normalized():
    """用于识别「是否为本项目 hook」的路径片段集合。"""
    roots = {str(repo_root()).replace("\\", "/")}
    env = os.environ.get("CC_TL_REPO_ROOT")
    if env:
        roots.add(env.replace("\\", "/").rstrip("/"))
    return roots


def hook_command(script: str, state: str, *extra: str) -> str:
    """
    生成红绿灯 hook 命令。

    - 开发模式：调用仓库根目录下的启动器 .py（薄封装），用当前解释器绝对路径
      （或 CC_TL_PYTHON），避免 IDE 子进程里找不到裸 `python` 导致 hook 静默失败。
    - 打包模式(sys.frozen)：调用打包出的 exe 自身 + 子命令(如 `VibeLight.exe set-state-unified auto`)，
      不依赖目标机的 Python 与 .py 源文件。
    集中在 launcher.app_command_str 里处理两种形态，见 claude_tl/launcher.py。

    extra 用于追加可选参数（如 `--event <事件名>`，让 set_state_unified 能按
    (agent, event) 查这个 hook 在三标签页里单独配的灯效）。
    """
    from claude_tl.launcher import app_command_str

    return app_command_str(script, state, *extra)


def command_hook(command, timeout=5):
    """生成 command hook 配置（Claude / Codex：嵌套 matcher + hooks 列表）。"""
    return {
        "type": "command",
        "command": command,
        "timeout": timeout,
    }


def hook_group(command, matcher="", timeout=5):
    """生成单个 matcher 的 hook 分组（Claude / Codex）。"""
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
    """只移除红绿灯自己的 hooks，保留用户已有的其它 hooks（Claude / Codex 嵌套结构）。"""
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


def remove_traffic_light_hooks_cursor(config):
    """移除 Cursor `hooks.json` 中的红绿灯项（扁平 `{ command, ... }` 列表）。"""
    hooks = config.get("hooks")
    if not isinstance(hooks, dict):
        return

    for event_name in list(hooks.keys()):
        items = hooks.get(event_name)
        if not isinstance(items, list):
            continue
        kept = []
        for item in items:
            if not isinstance(item, dict):
                kept.append(item)
                continue
            if is_traffic_light_hook(item):
                continue
            kept.append(item)
        if kept:
            hooks[event_name] = kept
        else:
            del hooks[event_name]

    if not hooks:
        config.pop("hooks", None)


def add_hook_groups(config, hook_groups):
    """追加红绿灯 hooks。调用前会先清理旧的红绿灯 hooks（Claude / Codex）。"""
    remove_traffic_light_hooks(config)
    hooks = config.setdefault("hooks", {})
    for event_name, groups in hook_groups.items():
        hooks.setdefault(event_name, []).extend(groups)


def add_cursor_hook_items(config, hook_items_by_event: dict):
    """追加 Cursor 扁平 hooks；调用前会先清理旧的红绿灯项。"""
    remove_traffic_light_hooks_cursor(config)
    if not isinstance(config, dict):
        return
    config.setdefault("version", 1)
    hooks = config.setdefault("hooks", {})
    for event_name, items in hook_items_by_event.items():
        hooks.setdefault(event_name, []).extend(items)


def claude_hook_groups():
    """Claude Code 的红绿灯 hooks（由 hook_light_catalog 声明，集中维护）。"""
    return iter_claude_wired_hook_groups(hook_command, hook_group)


def codex_hook_groups():
    """Codex 的红绿灯 hooks（由 hook_light_catalog 声明）。"""
    return iter_codex_wired_hook_groups(hook_command, hook_group)


def cursor_hook_items():
    """Cursor 的红绿灯 hooks（扁平列表项，见 Cursor 文档 hooks.json）。"""
    return iter_cursor_wired_hook_items(hook_command)


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


def set_cursor_hooks(enable):
    """启用或禁用 Cursor 的 traffic light hooks（用户级 ~/.cursor/hooks.json）。"""
    config = load_json_file(CURSOR_HOOKS_FILE)
    if not isinstance(config, dict):
        config = {}
    if enable:
        add_cursor_hook_items(config, cursor_hook_items())
    else:
        remove_traffic_light_hooks_cursor(config)
    config.setdefault("version", 1)
    save_json_file(CURSOR_HOOKS_FILE, config)


def switch_agent(agent):
    """切换到指定的 agent。"""
    config = load_config()

    if agent not in ["claude", "codex", "cursor"]:
        _safe_print(f"无效的 agent: {agent}，支持的值: claude, codex, cursor")
        return False

    current = config.get("active", "claude")
    if current == "claude":
        set_claude_hooks(False)
    elif current == "codex":
        set_codex_hooks(False)
    elif current == "cursor":
        set_cursor_hooks(False)

    if agent == "claude":
        set_claude_hooks(True)
    elif agent == "codex":
        set_codex_hooks(True)
    elif agent == "cursor":
        set_cursor_hooks(True)

    config["active"] = agent
    save_config(config)

    _safe_print(f"已切换到 {agent}")
    return True


def show_status():
    """显示当前状态。"""
    config = load_config()
    active = config.get("active", "claude")
    agents = config.get("agents", {})

    _safe_print(f"当前激活的 agent: {active}")
    _safe_print("Agent 配置:")
    for name, agent_config in agents.items():
        status = "ACTIVE 激活" if name == active else "  未激活"
        _safe_print(f"  {status} {name}: {agent_config.get('name', name)}")


def main():
    if len(sys.argv) < 2:
        _safe_print("用法:")
        _safe_print("  python switch_agent.py claude   # 切换到 Claude Code")
        _safe_print("  python switch_agent.py codex    # 切换到 OpenAI Codex")
        _safe_print("  python switch_agent.py cursor   # 切换到 Cursor")
        _safe_print("  python switch_agent.py status   # 查看当前状态")
        sys.exit(1)

    action = sys.argv[1]

    if action == "status":
        show_status()
    elif action in ["claude", "codex", "cursor"]:
        switch_agent(action)
    else:
        _safe_print(f"无效的操作: {action}")
        sys.exit(1)


if __name__ == "__main__":
    main()
