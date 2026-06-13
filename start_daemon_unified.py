"""根目录启动器 → `claude_tl.start_daemon_unified`。"""
from pathlib import Path
import sys

_SRC = Path(__file__).resolve().parent / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from claude_tl.start_daemon_unified import main

if __name__ == "__main__":
    main()
