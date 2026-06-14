"""Windows: 双击本文件由系统按 .pyw 关联启动（通常为 pythonw，无控制台）。"""
import runpy
from pathlib import Path

runpy.run_path(str(Path(__file__).resolve().parent / "vibelight_gui.py"), run_name="__main__")
