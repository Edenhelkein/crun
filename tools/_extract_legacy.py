import marshal
import importlib.util
import os
import shutil
import sys
import tempfile

from PyInstaller.archive.readers import ZlibArchiveReader

OUT = r"E:\DeepSeek\campus-run-assistant\legacy"
HDR = importlib.util.MAGIC_NUMBER + b"\0" * 12
OWN = ["AesUtils", "RsaUtils", "TiShiNengError", "TiShiNengRunPathManage", "TiShiNengSdkBase",
       "TiShiNengSdkPrivate", "TiShiNengSdkPublic", "database", "deviceModel", "device_profile",
       "models", "services", "spiderServer", "step_buckets", "track_clean", "track_geo",
       "track_log", "track_metrics", "track_resample", "track_validate", "tsnClient",
       "tsnRunServer", "tsn_environment", "tsn_face_schedule", "tsn_payload", "tsn_routes",
       "validCountServer"]

pyz = ZlibArchiveReader(os.path.join(tempfile.gettempdir(), "old.pyz"))
names = list(pyz.toc)
pkgs = {n for n in names if any(m.startswith(n + ".") for m in names)}

shutil.rmtree(OUT, ignore_errors=True)
os.makedirs(OUT, exist_ok=True)
n = 0
for name in names:
    if not any(name == o or name.startswith(o + ".") for o in OWN):
        continue
    rel = (name.replace(".", os.sep) + os.sep + "__init__.pyc") if name in pkgs else (name.replace(".", os.sep) + ".pyc")
    p = os.path.join(OUT, rel)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "wb") as f:
        f.write(HDR)
        f.write(marshal.dumps(pyz.extract(name)))
    n += 1
print("legacy modules written:", n)
print("packages:", sorted(p for p in pkgs if any(p == o or p.startswith(o + ".") for o in OWN)))
