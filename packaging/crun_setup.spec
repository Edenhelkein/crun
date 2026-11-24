# -*- mode: python ; coding: utf-8 -*-
"""安装器规格：把程序包打进去，输出 crun-setup-<ver>.exe（无控制台，带图标）。

版本号从 crun/__init__.py 读，版本资源现场生成，避免 CI 里升了版本、exe 资源还停在旧值。
"""
import os
import re

ROOT = os.path.dirname(SPECPATH)
with open(os.path.join(ROOT, "crun", "__init__.py"), encoding="utf-8") as f:
    VER = re.search(r'__version__\s*=\s*"([^"]+)"', f.read()).group(1)
PAYLOAD = os.path.join(ROOT, "dist", "release", "crun-%s-win64.zip" % VER)

# 现场生成版本资源
_vi = os.path.join(ROOT, "build_setup", "version_info_%s.txt" % VER)
os.makedirs(os.path.dirname(_vi), exist_ok=True)
with open(_vi, "w", encoding="utf-8") as f:
    f.write('''VSVersionInfo(
  ffi=FixedFileInfo(filevers=(%s), prodvers=(%s), mask=0x3f, flags=0x0,
                    OS=0x40004, fileType=0x1, subtype=0x0, date=(0,0)),
  kids=[
    StringFileInfo([StringTable(u'080404B0', [
      StringStruct(u'CompanyName', u'CRUN Studio'),
      StringStruct(u'FileDescription', u'CRUN 安装程序'),
      StringStruct(u'FileVersion', u'%s.0'),
      StringStruct(u'InternalName', u'crun-setup'),
      StringStruct(u'OriginalFilename', u'crun-setup-%s.exe'),
      StringStruct(u'ProductName', u'CRUN'),
      StringStruct(u'ProductVersion', u'%s.0')])]),
    VarFileInfo([VarStruct(u'Translation', [2052, 1200])])
  ])''' % (",".join(VER.split(".")) + ",0", ",".join(VER.split(".")) + ",0", VER, VER, VER))

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
    pyz, a.scripts, a.binaries, a.datas,
    [],
    name="crun-setup-%s" % VER,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    icon=os.path.join(ROOT, "packaging", "crun.ico"),
    version=_vi,
    manifest=os.path.join(ROOT, "packaging", "app.manifest"),
    uac_admin=False,
)
