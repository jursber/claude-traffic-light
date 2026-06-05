"""Traffic light configuration."""

import os
import serial.tools.list_ports

# Auto-detect ESP32C3 serial port by USB VID (Espressif)
ESP32_VID = 0x303A
DEFAULT_PORT = "COM3"
BAUD_RATE = 115200

def detect_port() -> str:
    for port in serial.tools.list_ports.comports():
        if port.vid == ESP32_VID:
            return port.device
    return DEFAULT_PORT

SERIAL_PORT = detect_port()

# State directory for multi-session IPC
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
    "alert":    1,
    "tools":    2,
    "working":  3,
    "model":    4,
    "thinking": 5,
    "idle":     6,
    "off":      7,
}
