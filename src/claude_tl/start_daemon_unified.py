"""
Unified daemon starter for Claude Code and OpenAI Codex.

Usage:
  python start_daemon_unified.py
"""

import ctypes
import os
import subprocess
import sys
from pathlib import Path

from claude_tl._paths import repo_root

PID_FILE = os.path.join(os.environ.get("LOCALAPPDATA", ""), "Temp", "cc_traffic_light_daemon.pid")


def daemon_script_path() -> str:
    """仓库根目录下的薄封装脚本（由根目录 daemon_unified.py 转发到包内逻辑）。"""
    return str(repo_root() / "daemon_unified.py")


def get_process_command_line(pid: int) -> str:
    """Read a process command line."""
    try:
        result = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                f"(Get-CimInstance Win32_Process -Filter \"ProcessId={pid}\").CommandLine",
            ],
            capture_output=True,
            text=True,
            timeout=3,
        )
    except Exception:
        return ""
    return result.stdout.strip()


def is_running():
    """Return True only when the PID file points to unified daemon entry."""
    if not os.path.exists(PID_FILE):
        return False

    try:
        with open(PID_FILE, "r", encoding="utf-8") as f:
            pid = int(f.read().strip())

        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if handle:
            kernel32.CloseHandle(handle)
            command_line = get_process_command_line(pid).replace("\\", "/").lower()
            return (
                "daemon_unified.py" in command_line
                or "unified_daemon" in command_line
                or ("-m claude_tl" in command_line and "daemon-unified" in command_line)
            )
    except (OSError, ValueError):
        pass

    return False


def start_daemon():
    """Start unified daemon if it is not already running."""
    if is_running():
        print("Daemon is already running")
        return True

    try:
        from claude_tl.launcher import daemon_spawn_argv, is_frozen

        argv = daemon_spawn_argv()
        cwd = str(Path(sys.executable).resolve().parent) if is_frozen() else str(repo_root())
        subprocess.Popen(
            argv,
            creationflags=subprocess.CREATE_NO_WINDOW,
            cwd=cwd,
        )
        print("Started unified traffic light daemon")
        return True
    except Exception as e:
        print(f"Failed to start daemon: {e}")
        return False


def main():
    success = start_daemon()
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
