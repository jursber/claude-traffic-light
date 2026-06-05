"""Traffic light daemon.

Holds serial port open, watches state file for changes.
Run once in background; hooks just write to the state file.

Usage: python daemon.py
"""

import os
import time
import serial
import sys

from config import SERIAL_PORT, BAUD_RATE, COMMANDS, STATE_FILE

POLL_INTERVAL = 0.05  # 50ms
PID_FILE = os.path.join(os.environ.get("LOCALAPPDATA", ""), "Temp", "cc_traffic_light_daemon.pid")

def main():
    # Write PID file
    with open(PID_FILE, "w") as f:
        f.write(str(os.getpid()))

    if not os.path.exists(STATE_FILE):
        with open(STATE_FILE, "w") as f:
            f.write("off")

    print(f"Opening {SERIAL_PORT}...", flush=True)
    try:
        ser = serial.Serial(SERIAL_PORT, BAUD_RATE, timeout=1, dsrdtr=False)
        ser.dtr = False
        ser.rts = False
    except serial.SerialException as e:
        print(f"Cannot open {SERIAL_PORT}: {e}", flush=True)
        sys.exit(1)

    print("Daemon running.", flush=True)
    last_state = None
    try:
        while True:
            try:
                with open(STATE_FILE, "r") as f:
                    state = f.read().strip()
            except FileNotFoundError:
                break

            if state != last_state:
                cmd = COMMANDS.get(state)
                if cmd:
                    ser.write(cmd.encode("ascii"))
                    ser.flush()
                    last_state = state

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
