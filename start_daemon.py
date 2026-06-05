"""Check if daemon is running, start it if not.

Called by CC SessionStart hook. Idempotent - safe to call multiple times.
"""

import os
import sys
import subprocess
import time

DAEMON_SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "daemon.py")
PID_FILE = os.path.join(os.environ.get("LOCALAPPDATA", ""), "Temp", "cc_traffic_light_daemon.pid")


def is_daemon_running() -> bool:
    if not os.path.exists(PID_FILE):
        return False
    try:
        with open(PID_FILE, "r") as f:
            pid = int(f.read().strip())
        # Check if process exists
        os.kill(pid, 0)
        return True
    except (OSError, ValueError):
        # Process not found or invalid PID
        try:
            os.remove(PID_FILE)
        except OSError:
            pass
        return False


def start_daemon() -> bool:
    try:
        proc = subprocess.Popen(
            [sys.executable, DAEMON_SCRIPT],
            creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NO_WINDOW,
            stdout=open(os.path.join(os.environ.get("LOCALAPPDATA", ""), "Temp", "cc_traffic_light_daemon.log"), "w"),
            stderr=subprocess.STDOUT,
        )
        with open(PID_FILE, "w") as f:
            f.write(str(proc.pid))
        # Wait briefly to check if it starts successfully
        time.sleep(0.5)
        if proc.poll() is not None:
            return False
        return True
    except Exception as e:
        print(f"Failed to start daemon: {e}", file=sys.stderr)
        return False


def main():
    if is_daemon_running():
        print("Daemon already running.")
        return

    if start_daemon():
        print("Daemon started.")
    else:
        print("Failed to start daemon.", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
