"""
打包(frozen)与开发(dev)两种形态下，统一生成「调用本项目某个子命令」的可执行命令。

为什么需要它：
  - 开发模式：用当前(或 CC_TL_PYTHON 指定的) Python 解释器去跑仓库根目录的薄封装 .py，
    例如 `python set_state_unified.py auto`；这要求目标机装了 Python 且有 .py 源文件。
  - PyInstaller 打包(sys.frozen=True)：目标机通常没有 Python、也没有 .py 源文件。此时改为
    直接用打包出的 exe 自身 + 子命令分发，例如 `VibeLight.exe set-state-unified auto`。
    打包入口(tools/tl_hook_light_gui.py)会在加载 GUI 之前识别这些子命令并转发到 __main__。

所有 hook 注册、daemon 拉起、开机自启都应通过这里生成命令，避免各处散落 frozen 判断。
"""

from __future__ import annotations

import os
import subprocess
import sys

from claude_tl._paths import repo_root

# 仓库根目录薄封装脚本名(开发模式) → 统一子命令(__main__.py 与打包入口都认)
SCRIPT_TO_SUBCOMMAND: dict[str, str] = {
    "set_state_unified.py": "set-state-unified",
    "set_state.py": "set-state",
    "set_alert_and_defer.py": "set-alert",
    "start_daemon_unified.py": "start-daemon-unified",
    "start_daemon.py": "start-daemon",
    "daemon_unified.py": "daemon-unified",
    "daemon.py": "daemon",
    "switch_agent.py": "switch-agent",
}

SUBCOMMAND_TO_SCRIPT: dict[str, str] = {v: k for k, v in SCRIPT_TO_SUBCOMMAND.items()}

# 打包入口据此判断 argv[1] 是否为「当 hook/daemon 用」的子命令
SUBCOMMANDS: frozenset[str] = frozenset(SCRIPT_TO_SUBCOMMAND.values())


def is_frozen() -> bool:
    """是否为 PyInstaller 等打包后的冻结可执行。"""
    return bool(getattr(sys, "frozen", False))


def python_executable() -> str:
    """开发模式下用于跑脚本的解释器；允许用 CC_TL_PYTHON 覆盖。"""
    return os.environ.get("CC_TL_PYTHON") or sys.executable


def _dev_root() -> str:
    """开发模式下薄封装脚本所在目录；CC_TL_REPO_ROOT 优先(多副本克隆场景)。"""
    return os.environ.get("CC_TL_REPO_ROOT") or str(repo_root())


def app_argv(script_or_subcmd: str, *args: str) -> list[str]:
    """
    生成可直接交给 subprocess 的 argv 列表。

    script_or_subcmd 既可传薄封装脚本名(如 'set_state_unified.py')，
    也可直接传子命令(如 'set-state-unified' / 'daemon-unified')。
    空字符串参数会被剔除，便于上层无脑追加可选 state 参数。
    """
    subcmd = SCRIPT_TO_SUBCOMMAND.get(script_or_subcmd, script_or_subcmd)
    extra = [a for a in args if a != "" and a is not None]

    if is_frozen():
        # 打包：exe 自身 + 子命令；不依赖目标机的 Python 或 .py 源文件
        return [sys.executable, subcmd, *extra]

    # 开发：优先跑仓库根薄封装(无需 pip install)，否则回退 `-m claude_tl`
    exe = python_executable()
    script = SUBCOMMAND_TO_SCRIPT.get(subcmd)
    root = _dev_root()
    if script:
        script_path = os.path.join(root, script)
        if os.path.isfile(script_path):
            return [exe, script_path, *extra]
    return [exe, "-m", "claude_tl", subcmd, *extra]


def app_command_str(script_or_subcmd: str, *args: str) -> str:
    """同 app_argv，但返回可写入 hooks.json 的命令字符串(已做 Windows 引号转义)。"""
    return subprocess.list2cmdline(app_argv(script_or_subcmd, *args))


def daemon_spawn_argv() -> list[str]:
    """
    后台拉起 unified daemon 用的 argv。

    开发模式优先用 pythonw(无控制台)；打包模式用 exe 自身 + 子命令(配合
    CREATE_NO_WINDOW 同样无黑框)。
    """
    if is_frozen():
        return [sys.executable, "daemon-unified"]
    exe = python_executable()
    # 尽量用 pythonw.exe，双保险(另有 CREATE_NO_WINDOW)避免控制台黑框
    if exe.lower().endswith("python.exe"):
        candidate = exe[: -len("python.exe")] + "pythonw.exe"
        if os.path.isfile(candidate):
            exe = candidate
    script = os.path.join(_dev_root(), "daemon_unified.py")
    if os.path.isfile(script):
        return [exe, script]
    return [exe, "-m", "claude_tl", "daemon-unified"]
