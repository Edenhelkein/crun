"""扫描 legacy/*.pyc 的 import，生成 hiddenimports（保留完整点号路径）。

原版模块以数据形式打包，PyInstaller 看不到它们内部的 import；
只收顶层名不够 —— `from ctypes.util import find_library` 需要 `ctypes.util`，
只收 `ctypes` 运行时就报 "No module named 'ctypes.util'"。
"""
import dis
import json
import marshal
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LEGACY = os.path.join(ROOT, "legacy")
OUT = os.path.join(ROOT, "legacy_imports.json")

# 这些包的内部 import 由 PyInstaller 自己的 hook 处理，别手动干扰
SKIP_TOP = {"Crypto", "PIL", "customtkinter", "sqlalchemy", "httpx", "anyio", "loguru",
            "greenlet", "rsa", "pyasn1", "aiosqlite", "sniffio", "h11", "httpcore",
            "certifi", "colorama", "idna"}


def _is_stdlib(name):
    top = name.split(".")[0]
    return top in sys.stdlib_module_names


def walk(code, out):
    for ins in dis.get_instructions(code):
        if ins.opname == "IMPORT_NAME":
            name = ins.argval
            if not name or name.startswith("_"):
                continue
            if _is_stdlib(name) and name.split(".")[0] not in SKIP_TOP:
                out.add(name)
                # 父包也补上，保证 import 链完整
                parts = name.split(".")
                for i in range(1, len(parts)):
                    out.add(".".join(parts[:i]))
    for const in code.co_consts:
        if hasattr(const, "co_code"):
            walk(const, out)


def main():
    names = set()
    files = 0
    for root in (os.path.join(ROOT, "legacy"), os.path.join(ROOT, "legacy_site")):
        if not os.path.isdir(root):
            continue
        for base, _dirs, fs in os.walk(root):
            for fn in fs:
                if not fn.endswith(".pyc"):
                    continue
                try:
                    with open(os.path.join(base, fn), "rb") as f:
                        f.seek(16)
                        walk(marshal.loads(f.read()), names)
                    files += 1
                except Exception:
                    continue
    keep = []
    for n in sorted(names):
        try:
            import importlib.util
            if importlib.util.find_spec(n) is None:
                continue          # 当前解释器里不存在（比如 3.14 才有的模块），放进 hiddenimports 只会告警
        except Exception:
            continue
        keep.append(n)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(keep, f, ensure_ascii=False, indent=2)
    print("scanned %d pyc -> %d modules" % (files, len(keep)))
    print(", ".join(keep))


if __name__ == "__main__":
    main()
