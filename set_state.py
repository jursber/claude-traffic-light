"""Called by hooks. Just writes state to file - daemon handles serial.

Usage: python set_state.py <state>
"""

import sys
import os

from config import COMMANDS, STATE_FILE

def set_state(state: str) -> bool:
    if state not in COMMANDS:
        return False
    try:
        tmp = STATE_FILE + ".tmp"
        with open(tmp, "w") as f:
            f.write(state)
        os.replace(tmp, STATE_FILE)
        return True
    except OSError:
        return False

if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(1)
    sys.exit(0 if set_state(sys.argv[1]) else 1)
