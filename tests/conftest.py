"""pytest：把 src 加入 path（与根目录薄启动器行为一致）。"""
from pathlib import Path

import sys

_ROOT = Path(__file__).resolve().parents[1]
_SRC = _ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))
