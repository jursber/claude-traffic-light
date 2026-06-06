"""
守护进程启动器 - 被 CC SessionStart hook 调用

功能：
  1. 检查守护进程是否已经在运行（通过 PID 文件 + Windows API 验证）
  2. 如果没运行，通过计划任务启动
  3. 幂等设计：多次调用安全，不会启动多个实例

为什么需要这个？
  守护进程通过启动文件夹的 VBScript 脚本运行，但有时会意外崩溃。
  CC 每次启动时调用这个脚本，确保护进程在运行。
"""

import os
import sys
import subprocess
import ctypes
import time

# 守护进程的 PID 文件路径
PID_FILE = os.path.join(os.environ.get("LOCALAPPDATA", ""), "Temp", "cc_traffic_light_daemon.pid")

# Windows 计划任务名称（用于启动守护进程）
TASK_NAME = "ClaudeTrafficLightDaemon"


def is_daemon_running() -> bool:
    """
    检查守护进程是否在运行。

    方法：
    1. 读取 PID 文件获取进程 ID
    2. 用 Windows API（OpenProcess）验证该进程是否还活着
    3. 如果进程不存在，清理过期的 PID 文件

    Returns:
        True 守护进程在运行，False 没在运行
    """
    if not os.path.exists(PID_FILE):
        return False
    try:
        with open(PID_FILE, "r") as f:
            pid = int(f.read().strip())
        # 用 Windows API 检查进程是否存在
        # PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(0x1000, False, pid)
        if handle:
            kernel32.CloseHandle(handle)
            return True
        # 进程不存在，清理过期 PID 文件
        return False
    except (OSError, ValueError):
        return False


def start_via_task():
    """
    通过 Windows 计划任务启动守护进程。

    计划任务 "ClaudeTrafficLightDaemon" 由 install_service.py 创建，
    配置为登录时自动启动、隐藏窗口。
    这里手动触发一次运行。
    """
    subprocess.run(["schtasks", "/Run", "/TN", TASK_NAME], capture_output=True)


def main():
    # 已经在运行，直接返回
    if is_daemon_running():
        print("守护进程已在运行。")
        return

    # 尝试通过计划任务启动
    print("正在启动守护进程...", flush=True)
    start_via_task()
    time.sleep(1)  # 等待进程启动

    # 再次检查是否成功启动
    if is_daemon_running():
        print("守护进程已启动。")
    else:
        print("启动失败。请以管理员身份运行 install_service.py 注册计划任务。", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
