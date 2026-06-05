"""Check if daemon is running via scheduled task. Start if not.

Called by CC SessionStart hook. Idempotent.
"""

import os
import sys
import subprocess
import ctypes

PID_FILE = os.path.join(os.environ.get("LOCALAPPDATA", ""), "Temp", "cc_traffic_light_daemon.pid")
TASK_NAME = "ClaudeTrafficLightDaemon"


def is_daemon_running() -> bool:
    if not os.path.exists(PID_FILE):
        return False
    try:
        with open(PID_FILE, "r") as f:
            pid = int(f.read().strip())
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if handle:
            kernel32.CloseHandle(handle)
            return True
        return False
    except (OSError, ValueError):
        return False


def start_via_task():
    """Start the scheduled task."""
    subprocess.run(["schtasks", "/Run", "/TN", TASK_NAME], capture_output=True)


def main():
    if is_daemon_running():
        print("Daemon already running.")
        return

    # Try to start via scheduled task
    start_via_task()
    import time
    time.sleep(1)

    if is_daemon_running():
        print("Daemon started via scheduled task.")
    else:
        print("Daemon not running. Run 'python install_service.py' as admin first.", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
