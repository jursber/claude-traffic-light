# -*- mode: python ; coding: utf-8 -*-
# 用法（在仓库根目录）:
#   pip install pyinstaller
#   pyinstaller packaging/pyinstaller/claude_tl.spec
# 产出 dist/claude-tl/claude-tl.exe（目录模式，便于放 active_agent.json 旁）

import sys
from pathlib import Path

SPECDIR = Path(SPECPATH).resolve().parent
ROOT = SPECDIR.parent.parent
ENTRY = SPECDIR / "entry.py"

block_cipher = None

a = Analysis(
    [str(ENTRY)],
    pathex=[str(ROOT / "src")],
    binaries=[],
    datas=[],
    hiddenimports=["bleak", "serial", "serial.tools.list_ports"],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="claude-tl",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="claude-tl",
)
