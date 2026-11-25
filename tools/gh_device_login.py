"""GitHub 设备码登录（一次点击完成授权）。

用户只需要：打开 https://github.com/login/device 输入终端打印的 8 位码。
成功后 token 落到 .gh_token（已 gitignore），供 gh / git push 使用。
"""
import json
import os
import sys
import time
import urllib.parse
import urllib.request

CLIENT_ID = "Iv1.b507a08c87ecfe98"      # GitHub CLI 的公开 OAuth 客户端
TOKEN_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".gh_token")


def post(url, data):
    req = urllib.request.Request(
        url, data=urllib.parse.urlencode(data).encode(),
        headers={"Accept": "application/json", "User-Agent": "crun-release"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


def main():
    r = post("https://github.com/login/device/code",
             {"client_id": CLIENT_ID, "scope": "repo read:user"})
    if "device_code" not in r:
        print("START_FAILED", json.dumps(r, ensure_ascii=False))
        return 1
    print("CODE " + r["user_code"], flush=True)
    print("URL  " + r["verification_uri"], flush=True)
    print("等待授权中…（有效期 %d 秒）" % r["expires_in"], flush=True)

    interval = int(r.get("interval", 5))
    deadline = time.time() + int(r["expires_in"])
    while time.time() < deadline:
        time.sleep(interval)
        try:
            t = post("https://github.com/login/oauth/access_token",
                     {"client_id": CLIENT_ID, "device_code": r["device_code"],
                      "grant_type": "urn:ietf:params:oauth:grant-type:device_code"})
        except Exception as e:
            print("poll error:", e, flush=True)
            continue
        if "access_token" in t:
            with open(TOKEN_FILE, "w", encoding="utf-8") as f:
                f.write(t["access_token"])
            print("TOKEN_OK", flush=True)
            return 0
        err = t.get("error")
        if err == "authorization_pending":
            continue
        if err == "slow_down":
            interval += 5
            continue
        print("ERR " + str(err), flush=True)
        return 1
    print("TIMEOUT", flush=True)
    return 1


if __name__ == "__main__":
    sys.exit(main())
