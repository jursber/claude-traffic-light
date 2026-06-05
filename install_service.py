"""Install traffic light daemon as a Windows scheduled task.

Runs at login, independent of CC sessions.
Usage: python install_service.py [--uninstall]
"""

import subprocess
import sys
import os

TASK_NAME = "ClaudeTrafficLightDaemon"
DAEMON_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "daemon.py")
PYTHON_PATH = sys.executable


def install():
    cmd = [
        "schtasks", "/Create", "/F",
        "/TN", TASK_NAME,
        "/TR", f'"{PYTHON_PATH}" "{DAEMON_PATH}"',
        "/SC", "ONLOGON",
        "/RL", "HIGHEST",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode == 0:
        print(f"Scheduled task '{TASK_NAME}' created.")
        # Run it now
        subprocess.run(["schtasks", "/Run", "/TN", TASK_NAME])
        print("Daemon started.")
    else:
        print(f"Failed: {result.stderr}", file=sys.stderr)
        sys.exit(1)


def uninstall():
    result = subprocess.run(
        ["schtasks", "/Delete", "/F", "/TN", TASK_NAME],
        capture_output=True, text=True,
    )
    if result.returncode == 0:
        print(f"Scheduled task '{TASK_NAME}' removed.")
    else:
        print(f"Failed: {result.stderr}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    if "--uninstall" in sys.argv:
        uninstall()
    else:
        install()
