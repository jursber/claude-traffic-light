"""Traffic light configuration."""

import os

# Serial port settings
SERIAL_PORT = "COM3"
BAUD_RATE = 115200

# State directory for multi-session IPC
# Each session writes its own file: {STATE_DIR}/{session_id}
STATE_DIR = os.path.join(os.environ.get("LOCALAPPDATA", ""), "Temp", "cc_tl_states")

# Serial commands sent to ESP32C3
COMMANDS = {
    "model":       "G",   # green blink   - calling model (API request)
    "working":     "g",   # green solid   - working (writing code etc.)
    "thinking":    "y",   # yellow blink  - thinking
    "tools":       "Y",   # yellow solid  - calling tools
    "alert":       "r",   # red blink     - needs permission OR error
    "idle":        "R",   # red solid     - finished reply, waiting for input
    "off":         "O",   # all off       - session ended
}

# Priority: lower number = higher priority (shown first)
PRIORITY = {
    "alert":    1,   # permission / error - needs immediate attention
    "tools":    2,   # calling tools
    "model":    3,   # calling model
    "thinking": 4,   # thinking
    "working":  5,   # working
    "idle":     6,   # waiting for input
    "off":      7,   # session ended
}
