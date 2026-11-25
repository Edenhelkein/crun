"""设备码登录（DNS 被污染时用固定 IP 直连）。

原理：只在本进程里把 github.com 等域名解析到可用 IP，不改系统 hosts、不需要管理员。
用法：python tools/gh_login_fast.py
成功后 token 存到 .gh_token（已 gitignore）。
"""
import json
import os
import socket
import ssl
import sys
import time
import urllib.parse
import urllib.request

PIN = {
    "github.com": "20.205.243.166",
    "api.github.com": "20.205.243.168",
    "codeload.github.com": "20.205.243.165",
    "objects.githubusercontent.com": "185.199.108.133",
}
CLIENT_ID = "Iv1.b507a08c87ecfe98"
TOKEN_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".gh_token")

_orig = socket.getaddrinfo


def patched(host, port, *a, **kw):
    ip = PIN.get(host)
    if ip:
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, port))]
    return _orig(host, port, *a, **kw)


socket.getaddrinfo = patched


def post(url, data=None, headers=None):
    body = urllib.parse.urlencode(data).encode() if data else b""
    req = urllib.request.Request(url, data=body,
                                 headers={"Accept": "application/json", "User-Agent": "crun-release",
                                          **(headers or {})})
    ctx = ssl.create_default_context()
    with urllib.request.urlopen(req, timeout=30, context=ctx) as r:
        return json.loads(r.read().decode("utf-8"))


def main():
    r = post("https://github.com/login/device/code",
             {"client_id": CLIENT_ID, "scope": "repo workflow read:user"})
    if "user_code" not in r:
        print("START_FAILED " + json.dumps(r, ensure_ascii=False))
        return 1
    print("CODE " + r["user_code"], flush=True)
    print("URL  " + r["verification_uri"], flush=True)
    interval = int(r.get("interval", 5))
    deadline = time.time() + int(r["expires_in"])
    while time.time() < deadline:
        time.sleep(interval)
        try:
            t = post("https://github.com/login/oauth/access_token",
                     {"client_id": CLIENT_ID, "device_code": r["device_code"],
                      "grant_type": "urn:ietf:params:oauth:grant-type:device_code"})
        except Exception as e:
            print("poll-retry " + type(e).__name__, flush=True)
            continue
        if "access_token" in t:
            with open(TOKEN_FILE, "w", encoding="utf-8") as f:
                f.write(t["access_token"])
            print("TOKEN_OK", flush=True)
            return 0
        if t.get("error") == "authorization_pending":
            continue
        if t.get("error") == "slow_down":
            interval += 5
            continue
        print("ERR " + str(t.get("error")), flush=True)
        return 1
    print("TIMEOUT", flush=True)
    return 1


if __name__ == "__main__":
    sys.exit(main())
