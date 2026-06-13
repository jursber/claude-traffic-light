"""根目录启动器 → V3 包 `claude_tl.daemon`（自动把 `src/` 加入 sys.path）。"""
from pathlib import Path
import sys

_SRC = Path(__file__).resolve().parent / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from claude_tl.daemon import main

if __name__ == "__main__":
    main()
