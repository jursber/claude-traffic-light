"""
统一守护进程启动器 - 支持 Claude Code 和 OpenAI Codex

功能：
  1. 检查 daemon 是否已在运行
  2. 如果没有运行，启动 daemon_unified.py
  3. 幂等设计，重复调用安全
"""

import os
import sys
import subprocess
import ctypes
import time

# 添加项目目录到路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

PID_FILE = os.path.join(os.environ.get("LOCALAPPDATA", ""), "Temp", "cc_traffic_light_daemon.pid")
TASK_NAME = "ClaudeTrafficLightDaemon"


def is_running():
    """检查 daemon 是否已在运行"""
    if not os.path.exists(PID_FILE):
        return False

    try:
        with open(PID_FILE, "r") as f:
            pid = int(f.read().strip())

        # 检查进程是否存在
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if handle:
            kernel32.CloseHandle(handle)
            return True
    except (OSError, ValueError):
        pass

    return False


def start_daemon():
    """启动 daemon"""
    if is_running():
        print("Daemon 已在运行")
        return True

    # 尝试通过计划任务启动
    try:
        result = subprocess.run(
            ["schtasks", "/Run", "/TN", TASK_NAME],
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            print("已通过计划任务启动 daemon")
            return True
    except Exception:
        pass

    # 直接启动
    try:
        daemon_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "daemon_unified.py")
        pythonw = sys.executable.replace("python.exe", "pythonw.exe")

        subprocess.Popen(
            [pythonw, daemon_path],
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        print("已直接启动 daemon")
        return True
    except Exception as e:
        print(f"启动 daemon 失败: {e}")
        return False


def main():
    success = start_daemon()
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
