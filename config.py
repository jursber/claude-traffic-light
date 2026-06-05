"""Traffic light configuration."""

# Serial port settings
SERIAL_PORT = "COM3"
BAUD_RATE = 115200

# State file for IPC between hook script and daemon
STATE_FILE = r"C:\Users\Administrator\AppData\Local\Temp\cc_traffic_light_state"

# Serial commands sent to ESP32C3
# Single character: G/Y/y/R/r/O
COMMANDS = {
    "idle":       "G",   # green solid - waiting for input
    "thinking":   "y",   # yellow blink - model processing
    "executing":  "Y",   # yellow solid - running tools
    "permission": "r",   # red blink - needs user approval
    "error":      "R",   # red solid - something failed
    "off":        "O",   # all off - session ended
}
