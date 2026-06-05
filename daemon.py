"""Traffic light daemon.

Holds serial port open, watches state directory for changes.
Aggregates all session states and displays the highest priority one.

Usage: python daemon.py
"""

import os
import time
import serial
import sys

from config import SERIAL_PORT, BAUD_RATE, COMMANDS, STATE_DIR, PRIORITY

POLL_INTERVAL = 0.05  # 50ms
PID_FILE = os.path.join(os.environ.get("LOCALAPPDATA", ""), "Temp", "cc_traffic_light_daemon.pid")


def read_all_states() -> dict:
    """Read all session state files, return {session_id: state}."""
    states = {}
    if not os.path.exists(STATE_DIR):
        return states
    for name in os.listdir(STATE_DIR):
        if name.endswith(".tmp"):
            continue
        path = os.path.join(STATE_DIR, name)
        try:
            with open(path, "r") as f:
                state = f.read().strip()
            if state in COMMANDS:
                states[name] = state
        except OSError:
            continue
    return states


def highest_priority(states: dict) -> str:
    """Return the state with the highest priority (lowest number)."""
    if not states:
        return "off"
    return min(states.values(), key=lambda s: PRIORITY.get(s, 99))


def main():
    # Write PID file
    with open(PID_FILE, "w") as f:
        f.write(str(os.getpid()))

    os.makedirs(STATE_DIR, exist_ok=True)

    print(f"Opening {SERIAL_PORT} (auto-detected)...", flush=True)
    try:
        ser = serial.Serial(SERIAL_PORT, BAUD_RATE, timeout=1, dsrdtr=False)
        ser.dtr = False
        ser.rts = False
    except serial.SerialException as e:
        print(f"Cannot open {SERIAL_PORT}: {e}", flush=True)
        sys.exit(1)

    print("Daemon running.", flush=True)
    last_cmd = None
    try:
        while True:
            states = read_all_states()
            best = highest_priority(states)
            cmd = COMMANDS.get(best, "O")

            if cmd != last_cmd:
                ser.write(cmd.encode("ascii"))
                ser.flush()
                last_cmd = cmd

            time.sleep(POLL_INTERVAL)
    except KeyboardInterrupt:
        pass
    finally:
        try:
            ser.write(COMMANDS["off"].encode("ascii"))
            ser.flush()
        except Exception:
            pass
        ser.close()
        try:
            os.remove(PID_FILE)
        except OSError:
            pass


if __name__ == "__main__":
    main()
