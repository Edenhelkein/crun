"""打包发布 + 生成更新清单。

用法:
  python tools/make_release.py --version 1.2.1 --out dist
  python tools/make_release.py --version 1.2.1 --out dist --url https://TARGET.example/crun/
  python tools/make_release.py --version 1.2.1 --out dist --key KEY_MATERIAL   # 打 HMAC 签名
"""
import argparse
import hashlib
import hmac
import json
import os
import re
import shutil
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--version", required=True)
    ap.add_argument("--out", default="dist")
    ap.add_argument("--url", default="")
    ap.add_argument("--key", default="")
    ap.add_argument("--min-from", default="1.0.0")
    ap.add_argument("--notes", nargs="*", default=[])
    a = ap.parse_args()

    out = os.path.abspath(os.path.join(ROOT, a.out))
    os.makedirs(out, exist_ok=True)
    stage = os.path.join(out, ".stage")
    shutil.rmtree(stage, ignore_errors=True)
    shutil.copytree(os.path.join(ROOT, "crun"), os.path.join(stage, "crun"),
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))

    init = os.path.join(stage, "crun", "__init__.py")
    with open(init, encoding="utf-8") as f:
        src = f.read()
    src = re.sub(r'__version__\s*=\s*"[^"]*"', f'__version__ = "{a.version}"', src, count=1)
    with open(init, "w", encoding="utf-8") as f:
        f.write(src)

    name = f"crun-{a.version}.zip"
    zp = os.path.join(out, name)
    with zipfile.ZipFile(zp, "w", zipfile.ZIP_DEFLATED) as z:
        for base, _dirs, files in os.walk(stage):
            for fn in files:
                full = os.path.join(base, fn)
                z.write(full, os.path.relpath(full, stage))
    shutil.rmtree(stage, ignore_errors=True)

    sha = hashlib.sha256(open(zp, "rb").read()).hexdigest()
    base_url = a.url.rstrip("/") + "/" if a.url else ""
    manifest = {
        "version": a.version,
        "min_from": a.min_from,
        "url": (base_url + name) if a.url else zp,
        "sha256": sha,
        "notes": a.notes or [f"crun {a.version}"],
    }
    if a.key:
        manifest["signature"] = hmac.new(a.key.encode(), f"{a.version}{sha}".encode(),
                                         hashlib.sha256).hexdigest()
    mp = os.path.join(out, "manifest.json")
    with open(mp, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
    print(json.dumps({"package": zp, "manifest": mp, "sha256": sha,
                      "size": os.path.getsize(zp)}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
