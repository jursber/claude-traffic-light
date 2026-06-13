"""
PyInstaller 入口：与 `python -m claude_tl` 行为一致。
打包命令见同目录 README 或仓库 docs/PYINSTALLER.md
"""

from claude_tl.__main__ import main

if __name__ == "__main__":
    main()
