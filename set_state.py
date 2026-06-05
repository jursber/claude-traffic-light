"""Called by hooks. Writes session-specific state file.

Reads session_id and tool_name from stdin JSON (provided by CC hooks).

Usage:
  echo '{"session_id":"abc"}' | python set_state.py idle
  echo '{"session_id":"abc","tool_name":"AskUserQuestion"}' | python set_state.py auto
"""

import sys
import os
import json

from config import COMMANDS, STATE_DIR

# Tools that should show "alert" instead of "working"
ALERT_TOOLS = {"AskUserQuestion"}


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
        print(f"Usage: {sys.argv[0]} <state|auto>", file=sys.stderr)
        sys.exit(1)

    state = sys.argv[1]

    # Read stdin JSON
    session_id = "default"
    tool_name = ""
    try:
        raw = sys.stdin.read().strip()
        if raw:
            data = json.loads(raw)
            session_id = data.get("session_id", "default")
            tool_name = data.get("tool_name", "")
    except (json.JSONDecodeError, EOFError, OSError):
        pass

    # Auto mode: decide state based on tool_name
    if state == "auto":
        if tool_name in ALERT_TOOLS:
            state = "alert"
        else:
            state = "working"

    sys.exit(0 if set_state(state, session_id) else 1)


if __name__ == "__main__":
    main()
