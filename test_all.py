"""Test all traffic light states via daemon.

Requires daemon.py to be running.
Usage: python test_all.py
"""

import os
import time

from config import COMMANDS, STATE_DIR

def write_state(state, session="test"):
    os.makedirs(STATE_DIR, exist_ok=True)
    path = os.path.join(STATE_DIR, session)
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        f.write(state)
    os.replace(tmp, path)

def clean_session(session):
    try:
        os.remove(os.path.join(STATE_DIR, session))
    except OSError:
        pass

def test(name, state, duration=2):
    print(f"  {name:15s} ({state:10s} -> '{COMMANDS[state]}') ... ", end="", flush=True)
    write_state(state)
    time.sleep(duration)
    print("OK")

def main():
    print("Traffic Light Test Suite")
    print("=" * 50)

    tests = [
        ("Green blink",    "model"),
        ("Green solid",    "working"),
        ("Yellow blink",   "thinking"),
        ("Red blink",      "alert"),
        ("Red solid",      "idle"),
        ("All off",        "off"),
    ]

    for name, state in tests:
        test(name, state, duration=2)

    # Multi-session priority test
    print("\n  Multi-session priority test ... ", end="", flush=True)
    write_state("idle", "session_a")      # priority 5
    write_state("alert", "session_b")     # priority 1
    time.sleep(1)
    clean_session("session_a")
    clean_session("session_b")
    time.sleep(0.5)
    print("OK (should have shown red blink)")

    print("  Rapid switch test ... ", end="", flush=True)
    for _ in range(3):
        for state in ["idle", "thinking", "working", "alert", "off"]:
            write_state(state)
            time.sleep(0.15)
    print("OK")

    write_state("off")
    clean_session("test")
    print("\n" + "=" * 50)
    print("All tests passed!")

if __name__ == "__main__":
    main()
