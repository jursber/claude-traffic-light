"""
Unified daemon starter for Claude Code and OpenAI Codex.

Usage:
  python start_daemon_unified.py
"""

import ctypes
import os
import subprocess
import sys


PID_FILE = os.path.join(os.environ.get("LOCALAPPDATA", ""), "Temp", "cc_traffic_light_daemon.pid")


def daemon_path():
    """Return the unified daemon path."""
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "daemon_unified.py")


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
    """Return True only when the PID file points to daemon_unified.py."""
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
            return "daemon_unified.py" in command_line
    except (OSError, ValueError):
        pass

    return False


def start_daemon():
    """Start daemon_unified.py if it is not already running."""
    if is_running():
        print("Daemon is already running")
        return True

    try:
        pythonw = sys.executable.replace("python.exe", "pythonw.exe")
        subprocess.Popen(
            [pythonw, daemon_path()],
            creationflags=subprocess.CREATE_NO_WINDOW,
            cwd=os.path.dirname(os.path.abspath(__file__)),
        )
        print("Started daemon_unified.py")
        return True
    except Exception as e:
        print(f"Failed to start daemon: {e}")
        return False


def main():
    success = start_daemon()
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
