"""
仓库根目录与配置文件路径（V3 布局）。

小白提示：
  - 「仓库根」= 含有 pyproject.toml、src/、active_agent.json 的那一层的文件夹。
  - 打包成 exe 后 sys.frozen 为真，此时数据目录为 exe 所在目录，可把 active_agent.json 放在 exe 旁。
  - 环境变量 CC_TL_HOME：若设置，则 active_agent.json 固定为 {CC_TL_HOME}/active_agent.json。
  - 环境变量 CC_TL_REPO_ROOT：用于 hook 里写的路径（多副本克隆时），一般不必设。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


def repo_root() -> Path:
    """
    开发：本仓库根目录。
    PyInstaller 单文件/单目录：可执行文件所在目录。
    """
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    # .../repo/src/claude_tl/_paths.py → parents[2] == repo
    return Path(__file__).resolve().parents[2]


def active_agent_path() -> Path:
    """active_agent.json 的绝对路径。"""
    home = os.environ.get("CC_TL_HOME")
    if home:
        return Path(home).expanduser().resolve() / "active_agent.json"
    return repo_root() / "active_agent.json"
