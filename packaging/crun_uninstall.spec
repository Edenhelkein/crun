# -*- mode: python ; coding: utf-8 -*-
"""独立卸载程序：crun-uninstall.exe（单文件、无控制台）。"""
import os

ROOT = os.path.dirname(SPECPATH)

a = Analysis(
    [os.path.join(ROOT, "packaging", "uninstall_entry.py")],
    pathex=[ROOT],
    binaries=[],
    datas=[],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["numpy", "pandas", "matplotlib", "scipy", "PyQt5", "PySide2"],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz, a.scripts, a.binaries, a.datas,
    [],
    name="crun-uninstall",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    icon=os.path.join(ROOT, "packaging", "crun.ico"),
    version=os.path.join(ROOT, "packaging", "version_info.txt"),
    manifest=os.path.join(ROOT, "packaging", "app.manifest"),
    uac_admin=False,
)
