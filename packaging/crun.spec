# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 规格：onedir（不要 onefile）+ 版本资源 + manifest + 图标 + 不打 UPX。

为什么是 onedir：
  1. onefile 会在 %TEMP% 释放并执行一个内嵌 exe，这是 Defender / 卡巴 / 火绒
     "Trojan:Win32/Wacatac.B!ml" 这类 ML 启发式最常见的触发形态；
  2. onedir 的启动更快，也方便用户自己核对文件；
  3. 更新模块本来就是整包替换，onedir 反而更契合。
"""
import os

ROOT = os.path.dirname(SPECPATH)

a = Analysis(
    [os.path.join(ROOT, 'packaging', 'entry.py')],
    pathex=[ROOT],
    binaries=[],
    datas=[
        (os.path.join(ROOT, 'crun', 'hooks.js'), 'crun'),
        (os.path.join(ROOT, 'crun', 'ui', 'index.html'), 'crun/ui'),
    ],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'tkinter', 'turtle', 'unittest', 'doctest', 'pydoc', 'pydoc_data',
        'test', 'lib2to3', 'numpy', 'pandas', 'PIL', 'matplotlib', 'scipy',
        'sqlite3', 'ftplib', 'imaplib', 'smtplib', 'multiprocessing.dummy',
    ],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='crun',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,                 # 关键：UPX 压缩 = 大量静态特征命中
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=os.path.join(ROOT, 'packaging', 'crun.ico'),
    version=os.path.join(ROOT, 'packaging', 'version_info.txt'),
    manifest=os.path.join(ROOT, 'packaging', 'app.manifest'),
    uac_admin=False,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='crun',
)
