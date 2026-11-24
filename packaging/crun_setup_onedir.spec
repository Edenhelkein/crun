# -*- mode: python ; coding: utf-8 -*-
"""安装器（onedir 版）：不往 %TEMP% 释放，任何受限环境都能跑。

产出 dist/installer_onedir/crun-setup/crun-setup.exe —— 分发时把这个目录打成一个 zip，
比 onefile 更容易过 AV（没有"自解压执行"的行为特征）。
"""
import os
import re

ROOT = os.path.dirname(SPECPATH)
with open(os.path.join(ROOT, "crun", "__init__.py"), encoding="utf-8") as f:
    VER = re.search(r'__version__\s*=\s*"([^"]+)"', f.read()).group(1)
PAYLOAD = os.path.join(ROOT, "dist", "release", "crun-%s-win64.zip" % VER)

a = Analysis(
    [os.path.join(ROOT, "packaging", "setup_entry.py")],
    pathex=[ROOT],
    binaries=[],
    datas=[(PAYLOAD, "payload"), (os.path.join(ROOT, "packaging", "crun.ico"), "icon.ico")],
    hiddenimports=["crun.migrate", "crun.blacklist", "crun.policy", "crun.routegen"],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["numpy", "pandas", "PIL", "matplotlib", "scipy", "unittest", "pydoc"],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name="crun-setup",
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

coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="crun-setup")
