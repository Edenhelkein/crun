"""按 co_filename 判定包结构，重新导出原版 exe 里的模块（纯 python 的 .pyc）。"""
import importlib.util
import marshal
import os
import shutil
import sys
import tempfile

from PyInstaller.archive.readers import ZlibArchiveReader

ROOT = r"E:\DeepSeek\campus-run-assistant"
HDR = importlib.util.MAGIC_NUMBER + b"\0" * 12
OWN = {"AesUtils", "RsaUtils", "TiShiNengError", "TiShiNengRunPathManage", "TiShiNengSdkBase",
       "TiShiNengSdkPrivate", "TiShiNengSdkPublic", "database", "deviceModel", "device_profile",
       "models", "services", "spiderServer", "step_buckets", "track_clean", "track_geo",
       "track_log", "track_metrics", "track_resample", "track_validate", "tsnClient",
       "tsnRunServer", "tsn_environment", "tsn_face_schedule", "tsn_payload", "tsn_routes",
       "validCountServer"}

pyz = ZlibArchiveReader(os.path.join(tempfile.gettempdir(), "old.pyz"))
std = set(sys.stdlib_module_names)


def is_pkg(co):
    fn = getattr(co, "co_filename", "") or ""
    return fn.replace("\\", "/").endswith("__init__.py")


def dump(out_dir, keep):
    shutil.rmtree(out_dir, ignore_errors=True)
    os.makedirs(out_dir, exist_ok=True)
    n = 0
    for name in pyz.toc:
        top = name.split(".")[0]
        if not keep(name, top):
            continue
        co = pyz.extract(name)
        rel = (name.replace(".", os.sep) + os.sep + "__init__.pyc") if is_pkg(co) else (name.replace(".", os.sep) + ".pyc")
        p = os.path.join(out_dir, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "wb") as f:
            f.write(HDR)
            f.write(marshal.dumps(co))
        n += 1
    return n


own_keep = lambda name, top: name.split(".")[0] in OWN
site_keep = lambda name, top: (not name.startswith("pyimod")) and top not in std and not top.startswith("_") and top not in OWN

print("legacy:", dump(os.path.join(ROOT, "legacy"), own_keep))
print("site  :", dump(os.path.join(ROOT, "legacy_site"), site_keep))
