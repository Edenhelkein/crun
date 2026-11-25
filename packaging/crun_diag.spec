# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 规格：onedir（不要 onefile）+ 版本资源 + manifest + 图标 + 不打 UPX。

为什么是 onedir：
  1. onefile 会在 %TEMP% 释放并执行一个内嵌 exe，这是 Defender / 卡巴 / 火绒
     "Trojan:Win32/Wacatac.B!ml" 这类 ML 启发式最常见的触发形态；
  2. onedir 的启动更快，也方便用户自己核对文件；
  3. 更新模块本来就是整包替换，onedir 反而更契合。
"""
import json
import os

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

ROOT = os.path.dirname(SPECPATH)

# CI 上仓库里只有 legacy_bundle.zip，这里现场展开；本地开发直接用 legacy/ 目录
_bundle = os.path.join(ROOT, "legacy_bundle.zip")
if (not os.path.isdir(os.path.join(ROOT, "legacy")) or
        not os.path.isdir(os.path.join(ROOT, "legacy_site"))) and os.path.exists(_bundle):
    import zipfile
    zipfile.ZipFile(_bundle).extractall(ROOT)

# 原版模块是以 .pyc 数据形式打进来的，PyInstaller 看不到它们内部的 import，
# 必须显式收集，否则运行时报 "No module named 'glob'/'uuid'"。
_STD_EXTRA = [
    "glob", "uuid", "sysconfig", "getpass", "secrets", "unicodedata", "csv", "tarfile",
    "zipfile", "platform", "multiprocessing", "xml", "email", "html", "http", "ssl",
    "sqlite3", "decimal", "fractions", "statistics", "string", "textwrap", "shlex",
    "tempfile", "webbrowser", "winreg", "ctypes", "struct", "array", "binascii", "zlib",
    "bz2", "lzma", "pickle", "copy", "pprint", "difflib", "fnmatch", "codecs", "locale",
    "signal", "atexit", "gc", "types", "weakref", "contextlib", "functools", "itertools",
    "collections", "operator", "re", "numbers", "abc", "warnings", "traceback", "pdb",
    "ast", "dis", "marshal", "importlib", "pkgutil", "runpy", "site", "cmath", "errno",
    "fcntl", "gettext", "gzip", "imghdr", "ipaddress", "linecache", "msvcrt", "netrc",
    "nturl2path", "opcode", "pkg_resources", "quopri", "select", "selectors", "socketserver",
    "stringprep", "termios", "token", "tokenize", "tracemalloc", "tty", "urllib",
]
_scanned = []
_p = os.path.join(ROOT, "legacy_imports.json")
if os.path.exists(_p):
    try:
        _scanned = json.load(open(_p, encoding="utf-8"))
    except Exception:
        _scanned = []

a = Analysis(
    [os.path.join(ROOT, 'packaging', 'entry.py')],
    pathex=[ROOT],
    binaries=[],
    datas=[
        (os.path.join(ROOT, 'crun', 'hooks.js'), 'crun'),
        (os.path.join(ROOT, 'crun', 'ui', 'index.html'), 'crun/ui'),
        (os.path.join(ROOT, 'assets', 'tsn_data.db'), 'assets'),
    ] + collect_data_files('customtkinter')
      + [(os.path.join(ROOT, 'legacy'), 'legacy'), (os.path.join(ROOT, 'legacy_site'), 'legacy_site')],
    hiddenimports=(['customtkinter', 'darkdetect', 'sqlite3', 'sysconfig']
                   + collect_submodules('customtkinter')
                   + sorted(set(_STD_EXTRA) | set(_scanned))),
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'unittest', 'doctest', 'pydoc', 'pydoc_data',
        'test', 'lib2to3', 'numpy', 'pandas', 'PIL', 'matplotlib', 'scipy',
        'ftplib', 'imaplib', 'smtplib', 'multiprocessing.dummy',
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
    name='crun-con',
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
    name='crun-con',
)
