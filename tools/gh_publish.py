"""把仓库内容通过 GitHub API 推上去（本机 DNS 被污染，git 直连不通，改用 api.github.com）。

用法：python tools/gh_publish.py --repo crun --tag v1.2.2
"""
import argparse
import base64
import json
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PIN = {
    "github.com": "20.205.243.166",
    "api.github.com": "20.205.243.168",
    "codeload.github.com": "20.205.243.165",
    "objects.githubusercontent.com": "185.199.108.133",
    "uploads.github.com": "uploads.github.com",
}
_orig = socket.getaddrinfo


def patched(host, port, *a, **kw):
    ip = PIN.get(host)
    if ip and ip[0].isdigit():
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, port))]
    return _orig(host, port, *a, **kw)


socket.getaddrinfo = patched


def token():
    p = os.path.join(ROOT, ".gh_token")
    if not os.path.exists(p):
        sys.exit("没有 .gh_token，先跑 tools/gh_login_fast.py")
    return open(p, encoding="utf-8").read().strip()


TK = token()


def api(method, path, data=None, raw=False):
    url = path if path.startswith("https://") else "https://api.github.com" + path
    body = json.dumps(data).encode() if data is not None else None
    req = urllib.request.Request(url, data=body, method=method, headers={
        "Authorization": f"token {TK}",
        "Accept": "application/vnd.github+json",
        "User-Agent": "crun-release",
        "Content-Type": "application/json",
    })
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            payload = r.read()
            return json.loads(payload) if payload else {}
    except urllib.error.HTTPError as e:
        msg = e.read().decode("utf-8", "ignore")
        if e.code == 404 and method == "GET":
            return None
        raise SystemExit(f"HTTP {e.code} {method} {url}\n{msg[:600]}")


def tracked_files():
    out = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True).stdout
    files = [l.strip() for l in out.splitlines() if l.strip()]
    return [f for f in files if os.path.isfile(os.path.join(ROOT, f))]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default="crun")
    ap.add_argument("--tag", default="v1.2.2")
    ap.add_argument("--desc", default="校园跑会话控制台：路线随机化 / 自审 / 风控账本 / 云更新")
    a = ap.parse_args()

    me = api("GET", "/user")
    owner = me["login"]
    print(f"账号: {owner}")

    repo = api("GET", f"/repos/{owner}/{a.repo}")
    if repo is None:
        repo = api("POST", "/user/repos", {"name": a.repo, "description": a.desc,
                                           "private": False, "auto_init": False,
                                           "has_wiki": False, "has_projects": False})
        print(f"仓库已创建: {repo['html_url']}")
    else:
        print(f"仓库已存在: {repo['html_url']}")

    files = tracked_files()
    print(f"上传 {len(files)} 个文件…")

    # 空仓库不能直接建 blob（409 Git Repository is empty）：先用 Contents API 打一个初始提交
    parent = None
    try:
        head = api("GET", f"/repos/{owner}/{a.repo}/commits/main")
    except SystemExit:
        head = None
    if head is None:
        readme = open(os.path.join(ROOT, "README.md"), "rb").read()
        api("PUT", f"/repos/{owner}/{a.repo}/contents/README.md", {
            "message": "init",
            "content": base64.b64encode(readme).decode()})
        head = api("GET", f"/repos/{owner}/{a.repo}/commits/main")
        print("空仓库已初始化")
    parent = head["sha"]

    tree = []
    for i, rel in enumerate(files, 1):
        blob = api("POST", f"/repos/{owner}/{a.repo}/git/blobs", {
            "content": base64.b64encode(open(os.path.join(ROOT, rel), "rb").read()).decode(),
            "encoding": "base64"})
        tree.append({"path": rel.replace("\\", "/"), "mode": "100644", "type": "blob", "sha": blob["sha"]})
        if i % 10 == 0 or i == len(files):
            print(f"  {i}/{len(files)}")

    t = api("POST", f"/repos/{owner}/{a.repo}/git/trees", {"tree": tree})
    c = api("POST", f"/repos/{owner}/{a.repo}/git/commits", {
        "message": "crun 1.2.2：小角度随机路线 / 平台硬约束 / UI / 云更新 / 安装器 / 旧数据迁移",
        "tree": t["sha"], "parents": [parent]})
    print(f"commit: {c['sha'][:10]}")

    try:
        api("POST", f"/repos/{owner}/{a.repo}/git/refs",
            {"ref": "refs/heads/main", "sha": c["sha"]})
        print("分支 main 已建立")
    except SystemExit:
        api("PATCH", f"/repos/{owner}/{a.repo}/git/refs/heads/main", {"sha": c["sha"], "force": True})
        print("分支 main 已更新")
    try:
        api("PATCH", f"/repos/{owner}/{a.repo}", {"default_branch": "main"})
    except SystemExit:
        pass

    # 打标签 -> 触发 release.yml
    tagobj = api("POST", f"/repos/{owner}/{a.repo}/git/tags", {
        "tag": a.tag, "message": f"crun {a.tag}", "object": c["sha"], "type": "commit"})
    try:
        api("POST", f"/repos/{owner}/{a.repo}/git/refs",
            {"ref": f"refs/tags/{a.tag}", "sha": tagobj["sha"]})
        print(f"标签 {a.tag} 已推送（触发 CI）")
    except SystemExit as e:
        print("标签已存在或推送失败：", str(e)[:120])

    print("\n仓库地址:", repo["html_url"])
    print("Actions :", f"{repo['html_url']}/actions")
    return 0


if __name__ == "__main__":
    sys.exit(main())
