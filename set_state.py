"""Called by hooks. Writes session-specific state file.

Reads session_id from stdin JSON (provided by CC hooks).
Each session gets its own file in STATE_DIR.

Usage: echo '{"session_id":"abc123"}' | python set_state.py <state>
"""

import sys
import os
import json

from config import COMMANDS, STATE_DIR


def set_state(state: str, session_id: str = "default") -> bool:
    if state not in COMMANDS:
        return False
    os.makedirs(STATE_DIR, exist_ok=True)
    state_file = os.path.join(STATE_DIR, session_id)
    try:
        tmp = state_file + ".tmp"
        with open(tmp, "w") as f:
            f.write(state)
        os.replace(tmp, state_file)
        return True
    except OSError:
        return False


def main():
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} <state>", file=sys.stderr)
        sys.exit(1)

    state = sys.argv[1]

    # Read session_id from stdin JSON
    session_id = "default"
    try:
        raw = sys.stdin.read().strip()
        if raw:
            data = json.loads(raw)
            session_id = data.get("session_id", "default")
    except (json.JSONDecodeError, EOFError, OSError):
        pass

    sys.exit(0 if set_state(state, session_id) else 1)


if __name__ == "__main__":
    main()
