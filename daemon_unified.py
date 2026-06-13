"""根目录启动器 → V3 包 `claude_tl.unified_daemon`。"""
from pathlib import Path
import sys

_SRC = Path(__file__).resolve().parent / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from claude_tl.unified_daemon import main

if __name__ == "__main__":
    main()
