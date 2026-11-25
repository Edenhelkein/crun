"""更新模块：清单校验 -> 下载 -> sha256 校验 -> 暂存 -> 原子替换 -> 回滚。

设计取舍：
- 不做"下载下来直接覆盖"：先写 staging，校验通过才换目录，失败回滚 backup。
- 清单里的 min_from 防止跨大版本跳级（数据结构可能不兼容）。
- 可选 HMAC 签名：manifest.signature = HMAC(KEY, version + sha256)，避免中间人改包。
"""
import contextlib
import hashlib
import hmac
import json
import os
import shutil
import socket
import time
import urllib.request
import zipfile

from . import __version__

MANIFEST_KEYS = ("version", "url", "sha256")

# 国内 DNS 污染 github.com 时的兜底解析（只在正常连接失败后启用，可用 CRUN_NO_PIN=1 关闭）
PIN_IPS = {
    "github.com": "20.205.243.166",
    "api.github.com": "20.205.243.168",
    "codeload.github.com": "20.205.243.165",
    "objects.githubusercontent.com": "185.199.108.133",
}


@contextlib.contextmanager
def _pinned_dns():
    if os.environ.get("CRUN_NO_PIN"):
        yield
        return
    orig = socket.getaddrinfo

    def patched(host, port, *a, **kw):
        ip = PIN_IPS.get(host)
        if ip:
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, port))]
        return orig(host, port, *a, **kw)

    socket.getaddrinfo = patched
    try:
        yield
    finally:
        socket.getaddrinfo = orig


def _with_pin_fallback(fn):
    """先按系统 DNS 走；失败（被污染/超时）再固定 IP 重试一次。"""
    try:
        return fn()
    except Exception as first:
        if os.environ.get("CRUN_NO_PIN"):
            raise
        try:
            with _pinned_dns():
                return fn()
        except Exception:
            raise first


def parse_version(v):
    parts = []
    for seg in str(v).strip().lstrip("v").split("."):
        num = "".join(ch for ch in seg if ch.isdigit())
        parts.append(int(num) if num else 0)
    while len(parts) < 3:
        parts.append(0)
    return tuple(parts[:3])


def _resolve_url(manifest_url, target):
    """清单里的 url 允许写相对文件名：GitHub Releases 的
    .../releases/latest/download/manifest.json 旁边就放着同名 zip，不用自建服务器。"""
    if not target:
        return target
    if target.startswith(("http://", "https://", "file://")) or os.path.isabs(target):
        return target
    if manifest_url.startswith(("http://", "https://")):
        base = manifest_url.rsplit("/", 1)[0]
        return f"{base}/{target}"
    return os.path.join(os.path.dirname(os.path.abspath(manifest_url)), target)


def _load(source, allow_http=False, manifest_url=None):
    """source: dict | http(s) URL | 本地路径。默认拒绝明文 http（防止中间人换包）。"""
    if isinstance(source, dict):
        return source
    if source.startswith("http://") and not allow_http:
        raise ValueError("拒绝明文 http 清单：请用 https:// 或显式 --allow-http（仅限内网自测）")
    if source.startswith(("http://", "https://")):
        def _get():
            with urllib.request.urlopen(source, timeout=15) as r:
                return json.loads(r.read().decode("utf-8"))
        return _with_pin_fallback(_get)
    with open(source, encoding="utf-8") as f:
        return json.load(f)


def check(source, current=None, allow_http=False, channel=None):
    current = current or __version__
    try:
        m = _load(source, allow_http=allow_http)
    except Exception as e:
        return {"ok": False, "error": str(e)}
    if not isinstance(m, dict):
        return {"ok": False, "error": "清单格式错误"}
    if isinstance(source, str) and "url" in m:
        m = dict(m)
        m["url"] = _resolve_url(source, m["url"])
    missing = [k for k in MANIFEST_KEYS if not m.get(k)]
    if missing:
        return {"ok": False, "error": f"清单缺少字段: {missing}"}
    if channel and m.get("channel") and m["channel"] != channel:
        return {"ok": False, "error": f"清单频道 {m['channel']} 与请求频道 {channel} 不符"}
    cur, latest = parse_version(current), parse_version(m["version"])
    min_from = m.get("min_from")
    compatible = True
    if min_from and parse_version(current) < parse_version(min_from):
        compatible = False
    return {"ok": True, "current": current, "latest": m["version"],
            "update_available": latest > cur,
            "compatible": compatible,
            "min_from": min_from,
            "channel": m.get("channel", "stable"),
            "notes": m.get("notes", []),
            "size": m.get("size"),
            "url": m["url"], "sha256": m["sha256"],
            "signature": m.get("signature")}


def _sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _download(url, dest):
    if url.startswith(("http://", "https://")):
        _with_pin_fallback(lambda: urllib.request.urlretrieve(url, dest))
    else:
        shutil.copyfile(url, dest)
    return dest


def _verify_signature(manifest, key):
    if not key:
        return True, "未配置签名密钥，跳过"
    expect = hmac.new(key.encode(), f"{manifest['version']}{manifest['sha256']}".encode(),
                      hashlib.sha256).hexdigest()
    ok = hmac.compare_digest(expect, str(manifest.get("signature", "")))
    return ok, "签名一致" if ok else "签名不匹配"


PRESERVE = {"ledger.json", "policy.json", "routes.json", "state.json",
            "out", "demo_run", "session.json", ".crun-update", "version.txt"}


def _installed_version(install_dir):
    """以磁盘上的版本为准（自更新时进程内 __version__ 已经过时）。

    支持两种布局：
      - 源码/便携包：install_dir/crun/__init__.py
      - 冻结发布包：install_dir/version.txt（由 publish.py 写入）
    """
    for p in (os.path.join(install_dir, "version.txt"),
              os.path.join(install_dir, "crun", "__init__.py")):
        try:
            if p.endswith(".txt"):
                with open(p, encoding="utf-8") as f:
                    return f.read().strip()
            with open(p, encoding="utf-8") as f:
                for line in f:
                    if line.startswith("__version__"):
                        return line.split("=", 1)[1].strip().strip("'\"")
        except OSError:
            continue
    return __version__


def _schedule_swap(install_dir, staging, version, pid):
    """进程占用 _internal 时无法原地换目录：落一个等本进程退出的批处理再换。"""
    cmd_path = os.path.join(install_dir, "apply-update.cmd")
    script = f"""@echo off
setlocal enabledelayedexpansion
set N=0
:wait
tasklist /FI "PID eq {pid}" /NH 2>nul | findstr /R /C:"\\<{pid}\\>" >nul
if not errorlevel 1 (
  set /a N+=1
  if !N! GEQ 120 goto force
  timeout /t 1 /nobreak >nul
  goto wait
)
:force
robocopy "{staging}" "{install_dir}" /E /MOVE /NFL /NDL /NJH /NJS >nul
> "{os.path.join(install_dir, 'version.txt')}" echo {version}
del /q "%~f0" >nul 2>&1
"""
    with open(cmd_path, "w", encoding="utf-8", newline="\r\n") as f:
        f.write(script)
    import subprocess
    DETACHED_PROCESS = 0x00000008
    CREATE_NEW_PROCESS_GROUP = 0x00000200
    # 必须把 stdio 断开：否则父进程的管道被这个后台批处理继承，调用方会一直等 EOF
    subprocess.Popen(["cmd", "/c", cmd_path], creationflags=DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP,
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     close_fds=True)
    return {"ok": True, "stage": "pending-restart", "to": version, "layout": "frozen",
            "note": "程序退出后由 apply-update.cmd 完成替换并重启"}


def cleanup_leftovers(install_dir):
    """清掉上次更新残留（.crun-backup-*、.crun-update）。正在运行的进程可能还锁着，失败就下次再清。"""
    removed = []
    try:
        items = os.listdir(install_dir)
    except OSError:
        return removed
    for item in items:
        if item.startswith(".crun-backup") or item == ".crun-update":
            p = os.path.join(install_dir, item)
            shutil.rmtree(p, ignore_errors=True)
            if not os.path.exists(p):
                removed.append(item)
    return removed


def _is_locked(path):
    """判断文件是否被占用：能改名再改回来 = 没被锁。"""
    if not os.path.exists(path):
        return False
    tmp = path + ".probe"
    try:
        os.rename(path, tmp)
        os.rename(tmp, path)
        return False
    except OSError:
        try:
            if os.path.exists(tmp):
                os.rename(tmp, path)
        except OSError:
            pass
        return True


def _apply_frozen(install_dir, staging, version):
    """冻结版目录替换：换 _internal + exe，保留用户数据。

    两个分支：
      - 文件被占用（自己更新自己）-> 落批处理，退出后替换并重启
      - 没人占用            -> 直接换目录，失败完整回滚
    """
    new_root = staging
    if not os.path.exists(os.path.join(new_root, "crun.exe")):
        return {"ok": False, "stage": "layout", "error": "发布包缺少 crun.exe"}

    cleanup_leftovers(install_dir)

    if _is_locked(os.path.join(install_dir, "crun.exe")):
        return _schedule_swap(install_dir, new_root, version, os.getpid())

    backup = os.path.join(install_dir, f".crun-backup-{int(time.time())}")
    os.makedirs(backup, exist_ok=True)
    moved = []

    def restore():
        for item in list(os.listdir(install_dir)):
            if item in PRESERVE or item.startswith(".crun-backup"):
                continue
            p = os.path.join(install_dir, item)
            try:
                shutil.rmtree(p) if os.path.isdir(p) else os.remove(p)
            except OSError:
                pass
        for item in reversed(moved):
            try:
                shutil.move(os.path.join(backup, item), os.path.join(install_dir, item))
            except OSError as e:
                return f"{item}: {e}"
        return None

    try:
        for item in os.listdir(install_dir):
            if item in PRESERVE or item.startswith(".crun-backup"):
                continue
            shutil.move(os.path.join(install_dir, item), os.path.join(backup, item))
            moved.append(item)

        for item in os.listdir(new_root):
            shutil.move(os.path.join(new_root, item), os.path.join(install_dir, item))

        with open(os.path.join(install_dir, "version.txt"), "w", encoding="utf-8") as f:
            f.write(version)

        import subprocess
        out = subprocess.run([os.path.join(install_dir, "crun.exe"), "version"],
                             capture_output=True, text=True, timeout=30).stdout.strip()
        if out != version:
            raise RuntimeError(f"自检失败：新 exe 报 {out!r}，期望 {version!r}")
    except Exception as e:
        err = restore()
        shutil.rmtree(backup, ignore_errors=True)
        return {"ok": False, "stage": "swap-frozen",
                "error": str(e) + (f"（回滚异常 {err}）" if err else ""), "rolled_back": True}

    shutil.rmtree(backup, ignore_errors=True)
    return {"ok": True, "stage": "done", "from": "frozen", "to": version, "layout": "frozen"}


def apply(manifest, install_dir, dry_run=False, key=None, keep_backup=True, allow_http=False):
    """manifest 可以是 dict 或 check() 的返回（后者用 latest 字段表示新版本）。"""
    m = manifest if "url" in manifest and "sha256" in manifest else manifest.get("manifest", manifest)
    m = dict(m)
    if "version" not in m and "latest" in m:
        m["version"] = m["latest"]
    current = _installed_version(install_dir)
    if str(m.get("url", "")).startswith("http://") and not allow_http:
        return {"ok": False, "stage": "validate", "error": "拒绝明文 http 下载源"}
    if not m.get("url") or not m.get("sha256"):
        return {"ok": False, "stage": "validate", "error": "manifest 不完整"}

    latest = parse_version(m["version"])
    if latest <= parse_version(current):
        return {"ok": False, "stage": "validate", "error": f"当前版本 {current} 不低于 {m['version']}"}

    ok_sig, sig_msg = _verify_signature(m, key)
    if not ok_sig:
        return {"ok": False, "stage": "signature", "error": sig_msg}

    if dry_run:
        return {"ok": True, "stage": "dry-run", "from": current, "to": m["version"],
                "signature": sig_msg, "url": m["url"], "sha256": m["sha256"]}

    work = os.path.join(install_dir, ".crun-update")
    shutil.rmtree(work, ignore_errors=True)
    os.makedirs(work, exist_ok=True)
    archive = os.path.join(work, "pkg.zip")

    try:
        _download(m["url"], archive)
    except Exception as e:
        return {"ok": False, "stage": "download", "error": str(e)}

    digest = _sha256_file(archive)
    if digest.lower() != str(m["sha256"]).lower():
        return {"ok": False, "stage": "verify", "error": f"sha256 不符：{digest}"}

    staging = os.path.join(work, "stage")
    try:
        with zipfile.ZipFile(archive) as z:
            z.extractall(staging)
    except Exception as e:
        return {"ok": False, "stage": "extract", "error": str(e)}

    # 两种发布形态：源码/便携包（crun/ 包）与冻结发布包（crun.exe + _internal）
    if os.path.exists(os.path.join(staging, "crun.exe")):
        return _apply_frozen(install_dir, staging, m["version"])

    # 允许 zip 里带一层 crun/ 或直接是文件
    src = os.path.join(staging, "crun") if os.path.isdir(os.path.join(staging, "crun")) else staging
    if not os.path.exists(os.path.join(src, "__init__.py")):
        return {"ok": False, "stage": "layout", "error": "包结构不符：缺少 __init__.py"}

    target = os.path.join(install_dir, "crun")
    backup = os.path.join(work, f"backup-{int(time.time())}")
    try:
        if os.path.isdir(target):
            shutil.move(target, backup)
        shutil.move(src, target)
    except Exception as e:
        if os.path.isdir(backup) and not os.path.isdir(target):
            shutil.move(backup, target)   # 回滚
        return {"ok": False, "stage": "swap", "error": str(e), "rolled_back": True}

    # 换完自检：能 import 且版本号正确
    init_py = os.path.join(target, "__init__.py")
    with open(init_py, encoding="utf-8") as f:
        head = f.read()
    if f'"{m["version"]}"' not in head:
        shutil.rmtree(target, ignore_errors=True)
        if os.path.isdir(backup):
            shutil.move(backup, target)
        return {"ok": False, "stage": "selfcheck", "error": "版本号校验失败，已回滚", "rolled_back": True}

    if not keep_backup:
        shutil.rmtree(backup, ignore_errors=True)
    shutil.rmtree(work, ignore_errors=True)
    return {"ok": True, "stage": "done", "from": __version__, "to": m["version"],
            "backup": backup if keep_backup else None, "signature": sig_msg}
