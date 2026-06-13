"""根目录启动器 → `claude_tl.set_alert_and_defer`。"""
from pathlib import Path
import sys

_SRC = Path(__file__).resolve().parent / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from claude_tl.set_alert_and_defer import main

if __name__ == "__main__":
    main()
