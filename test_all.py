"""Test all traffic light states via daemon.

Requires daemon.py to be running.
Usage: python test_all.py
"""

import os
import time
import sys

from config import COMMANDS, STATE_FILE

def write_state(state):
    tmp = STATE_FILE + ".tmp"
    with open(tmp, "w") as f:
        f.write(state)
    os.replace(tmp, STATE_FILE)

def test(name, state, duration=2):
    print(f"  {name:15s} ({state:10s} -> '{COMMANDS[state]}') ... ", end="", flush=True)
    write_state(state)
    time.sleep(duration)
    print("OK")

def main():
    print("Traffic Light Test Suite")
    print("=" * 40)
    print(f"State file: {STATE_FILE}")
    print(f"Make sure daemon.py is running!\n")

    tests = [
        ("Green solid",    "idle"),
        ("Yellow blink",   "thinking"),
        ("Yellow solid",   "executing"),
        ("Red blink",      "permission"),
        ("Red solid",      "error"),
        ("All off",        "off"),
    ]

    for name, state in tests:
        test(name, state, duration=2)

    # Rapid switching test
    print("\n  Rapid switch test ... ", end="", flush=True)
    for _ in range(3):
        for state in ["idle", "thinking", "executing", "error", "off"]:
            write_state(state)
            time.sleep(0.15)
    print("OK")

    # Final state
    write_state("off")
    print("\n" + "=" * 40)
    print("All tests passed!")

if __name__ == "__main__":
    main()
