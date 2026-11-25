"""把 dist/win/crun 打成发布包，并生成更新清单。

用法:
  python tools/publish.py --version 1.2.2 --url https://TARGET.example/crun/
  python tools/publish.py --version 1.2.2 --url https://TARGET.example/crun/ --key KEY_MATERIAL
  python tools/publish.py --version 1.2.2 --upload-repo OWNER/REPO --tag v1.2.2   # 需要 gh 已登录
"""
import argparse
import hashlib
import hmac
import json
import os
import shutil
import subprocess
import sys
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def zip_dir(src, dst):
    """打包时在 zip 里套一层同名文件夹：用户解压/拖动时不会散成一地文件。"""
    top = os.path.splitext(os.path.basename(dst))[0]
    with zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for base, _dirs, files in os.walk(src):
            for fn in files:
                full = os.path.join(base, fn)
                rel = os.path.relpath(full, src).replace("\\", "/")
                z.write(full, f"{top}/{rel}")
    return dst


def main():
    for _s in (sys.stdout, sys.stderr):
        try:
            _s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    ap = argparse.ArgumentParser()
    ap.add_argument("--version", required=True)
    ap.add_argument("--channel", default="stable")
    ap.add_argument("--url", default="", help="发布目录的 https 前缀，清单里会写 <url>/<zip>")
    ap.add_argument("--key", default="", help="HMAC 密钥，设置后清单带 signature")
    ap.add_argument("--min-from", default="1.0.0")
    ap.add_argument("--notes", nargs="*", default=[])
    ap.add_argument("--src", default=os.path.join(ROOT, "dist", "win", "crun"))
    ap.add_argument("--out", default=os.path.join(ROOT, "dist", "release"))
    ap.add_argument("--upload-repo")
    ap.add_argument("--tag")
    ap.add_argument("--github-repo", help="OWNER/REPO：清单里只写文件名，客户端从 releases 解析")
    ap.add_argument("--installer", default="", help="安装器 exe 路径，一并上传")
    a = ap.parse_args()

    if not os.path.isdir(a.src):
        sys.exit(f"没有找到 {a.src}，先跑 tools/build_exe.ps1")
    os.makedirs(a.out, exist_ok=True)

    # 冻结包靠 version.txt 判断"磁盘上装的是哪一版"，必须写进包里
    exe = os.path.join(a.src, "crun.exe")
    real = ""
    if os.path.exists(exe):
        try:
            real = subprocess.run([exe, "version"], capture_output=True, text=True, timeout=30).stdout.strip()
        except Exception:
            real = ""
        if real and real != a.version:
            sys.exit(f"版本不一致：exe 报 {real}，清单要写 {a.version}。"
                     f"先把 crun/__init__.py 改成 {a.version} 再重新构建，避免发出去的包版本号对不上")
    with open(os.path.join(a.src, "version.txt"), "w", encoding="utf-8") as f:
        f.write(a.version + "\n")

    name = f"crun-{a.version}-win64.zip"
    zp = os.path.join(a.out, name)
    zip_dir(a.src, zp)
    digest = sha256(zp)

    manifest = {
        "version": a.version,
        "channel": a.channel,
        "min_from": a.min_from,
        "url": (a.url.rstrip("/") + "/" + name) if a.url else name,
        "sha256": digest,
        "size": os.path.getsize(zp),
        "notes": a.notes or [f"crun {a.version}"],
    }
    if a.key:
        manifest["signature"] = hmac.new(a.key.encode(), f"{a.version}{digest}".encode(),
                                         hashlib.sha256).hexdigest()
    mp = os.path.join(a.out, "manifest.json")
    with open(mp, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)

    out = {"package": zp, "manifest": mp, "sha256": digest,
           "size_mb": round(os.path.getsize(zp) / 1048576, 2)}
    print(json.dumps(out, ensure_ascii=False, indent=2))
    print(f"\n自查: python -m crun.cli doctor")
    print(f"提交误报/查毒: https://www.virustotal.com/gui/home/upload （先传，确认无误报再发）")

    if a.upload_repo:
        tag = a.tag or f"v{a.version}"
        assets = [zp, mp] + ([a.installer] if a.installer and os.path.exists(a.installer) else [])
        try:
            subprocess.run(["gh", "release", "create", tag] + assets +
                            ["--repo", a.upload_repo, "--title", f"crun {a.version}",
                             "--notes", "\n".join(manifest["notes"])], check=True)
            print(f"已发布到 {a.upload_repo} {tag}")
        except FileNotFoundError:
            print("未安装 gh CLI，跳过上传（可手动上传 zip 与 manifest.json）")
        except subprocess.CalledProcessError as e:
            print(f"gh 上传失败: {e}")

    repo = a.github_repo or a.upload_repo
    if repo:
        print(f"\n客户端更新源（固定不变）:")
        print(f"  https://github.com/{repo}/releases/latest/download/manifest.json")
        print(f"客户端命令: crun update --github {repo} --apply")


if __name__ == "__main__":
    main()
