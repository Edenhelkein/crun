"""把原版 exe 里的第三方模块也导出成可导入的 .pyc（包结构要正确）。"""
import importlib.util
import marshal
import os
import shutil
import sys
import tempfile

from PyInstaller.archive.readers import ZlibArchiveReader

OUT = r"E:\DeepSeek\campus-run-assistant\legacy_site"
HDR = importlib.util.MAGIC_NUMBER + b"\0" * 12

pyz = ZlibArchiveReader(os.path.join(tempfile.gettempdir(), "old.pyz"))
names = list(pyz.toc)
pkgs = {n for n in names if any(m.startswith(n + ".") for m in names)}
std = set(sys.stdlib_module_names)

shutil.rmtree(OUT, ignore_errors=True)
os.makedirs(OUT, exist_ok=True)
n = 0
for name in names:
    top = name.split(".")[0]
    if name.startswith("pyimod") or top in std or top.startswith("_"):
        continue
    rel = (name.replace(".", os.sep) + os.sep + "__init__.pyc") if name in pkgs else (name.replace(".", os.sep) + ".pyc")
    p = os.path.join(OUT, rel)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    try:
        with open(p, "wb") as f:
            f.write(HDR)
            f.write(marshal.dumps(pyz.extract(name)))
        n += 1
    except Exception:
        pass
print("site modules written:", n)
