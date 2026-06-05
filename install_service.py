"""Install traffic light daemon as a Windows scheduled task.

Runs at login, hidden window via pythonw.exe.
Usage: python install_service.py [--uninstall]
"""

import subprocess
import sys
import os
import tempfile

TASK_NAME = "ClaudeTrafficLightDaemon"
DAEMON_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "daemon.py")
PYTHONW = sys.executable.replace("python.exe", "pythonw.exe")

# Use InteractiveToken + Hidden to allow COM port access without visible window
TASK_XML = f"""<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <Settings>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <ExecutionTimeLimit>PT0S</ExecutionTimeLimit>
    <Hidden>true</Hidden>
  </Settings>
  <Triggers>
    <LogonTrigger>
      <Enabled>true</Enabled>
    </LogonTrigger>
  </Triggers>
  <Actions Context="Author">
    <Exec>
      <Command>"{PYTHONW}"</Command>
      <Arguments>"{DAEMON_PATH}"</Arguments>
    </Exec>
  </Actions>
  <Principals>
    <Principal id="Author">
      <LogonType>InteractiveToken</LogonType>
      <RunLevel>HighestAvailable</RunLevel>
    </Principal>
  </Principals>
</Task>"""


def install():
    subprocess.run(["schtasks", "/Delete", "/F", "/TN", TASK_NAME],
                    capture_output=True)

    xml_path = os.path.join(tempfile.gettempdir(), "cc_tl_task.xml")
    with open(xml_path, "w", encoding="utf-16") as f:
        f.write(TASK_XML)

    result = subprocess.run(
        ["schtasks", "/Create", "/F", "/TN", TASK_NAME, "/XML", xml_path],
        capture_output=True, text=True,
    )
    os.remove(xml_path)

    if result.returncode == 0:
        subprocess.run(["schtasks", "/Run", "/TN", TASK_NAME], capture_output=True)
        print(f"Scheduled task '{TASK_NAME}' created.")
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
