# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller 打包配置（onedir，console=True）。

设计要点：
  - 单一可执行文件同时充当三种角色：双击=GUI；`VibeLight.exe daemon-unified`=守护进程；
    `VibeLight.exe set-state-unified auto`=hook。角色分发在入口最早期完成（见 tools/tl_hook_light_gui.py 顶部）。
  - console=True：保证以 hook 身份被 IDE 调用时拥有可读的 stdin（IDE 把事件 JSON 通过管道送入）。
    GUI 启动时会自动隐藏控制台窗口（_win_detach_console_if_any），所以双击不会留黑框。
  - 不预置 active_agent.json / GUI 配置：首次运行时自动在 exe 旁生成，避免 onedir 的 _internal 路径问题。

构建：在仓库根执行 `pyinstaller packaging/vibelight.spec --noconfirm`
（或直接跑 packaging/build_win.ps1）。产物在 dist/VibeLight/VibeLight.exe。
"""

import os

from PyInstaller.utils.hooks import collect_submodules

# SPECPATH 由 PyInstaller 注入，指向本 spec 所在目录；仓库根 = 其上一层
ROOT = os.path.abspath(os.path.join(SPECPATH, os.pardir))
SRC = os.path.join(ROOT, "src")
ENTRY = os.path.join(ROOT, "tools", "tl_hook_light_gui.py")

hiddenimports = []
hiddenimports += collect_submodules("claude_tl")
hiddenimports += [
    "serial",
    "serial.tools",
    "serial.tools.list_ports",
    "pystray",
    "pystray._win32",
    "PIL",
    "PIL.Image",
    "PIL.ImageDraw",
    "PIL._tkinter_finder",
]

# BLE 为可选传输（CC_TL_TRANSPORT=ble 才用），装了 bleak 才打进去；没装也能用串口模式
try:
    import bleak  # noqa: F401

    hiddenimports += collect_submodules("bleak")
except Exception:
    pass


a = Analysis(
    [ENTRY],
    pathex=[SRC, ROOT],
    binaries=[],
    datas=[],
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="VibeLight",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,  # 保证 hook 身份有 stdin；GUI 启动会自动隐藏控制台
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="VibeLight",
)
