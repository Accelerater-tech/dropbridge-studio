"""在没有可用 git 传输的网络里，用 GitHub REST API 把仓库内容推上去。

背景：本机 DNS 被污染 / 443 被拦，`git push` 连不上 github.com，
但 `api.github.com` 是通的。于是改用 Git Data API 逐层提交：
blob → tree → commit → refs。提交者与作者都写成项目主人。

用法：GH_TOKEN=xxx python tools/gh_api_push.py [--repo dropbridge-studio] [--branch main]
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

API = "https://api.github.com"
AUTHOR_NAME = "Tomorin"
AUTHOR_EMAIL = "69080776+Accelerater-tech@users.noreply.github.com"
MESSAGE = """DropBridge Studio: 给 DropBridge 后端做一个图形化驾驶舱

按依赖顺序自动拉起 radio → bridge → netd → awdld → receiver，把后端日志
实时解析成指标，断线自动重启，并提供一键体检、自测接收、事件时间线、
诊断报告 / 抓一次实测留证、托盘常驻与开机自启。

- app/   控制器（配置、链路管理、体检、自测、托盘、pywebview js_api、CLI）
- web/   界面（原生 HTML/CSS/JS，WebView2）
- tools/ CDP 截图、假发送端、探针、便携版打包
- 免安装版 tools/make_portable.py（自带 CPython 3.12）

后端二进制与驱动来自上游 DropBridge (MIT)，本项目只做控制与界面。
"""


def api(path: str, token: str, method: str = "GET", payload: dict | None = None) -> tuple[int, dict]:
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(API + path, data=data, method=method)
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("User-Agent", "dropbridge-studio")
    if data:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return resp.status, json.loads(resp.read().decode() or "{}")
    except urllib.error.HTTPError as err:
        body = err.read().decode(errors="replace")
        try:
            return err.code, json.loads(body)
        except ValueError:
            return err.code, {"raw": body[:400]}
    except urllib.error.URLError as err:
        return 0, {"error": str(err)[:300]}


def tracked_files(root: Path) -> list[Path]:
    out = subprocess.run(["git", "ls-files", "-z"], cwd=root, capture_output=True)
    names = [n for n in out.stdout.decode("utf-8").split("\0") if n]
    if not names:  # 还没 add 过，就按 .gitignore 自己找
        names = [str(p.relative_to(root)).replace("\\", "/")
                 for p in sorted(root.rglob("*"))
                 if p.is_file() and ".git" not in p.parts and "data" not in p.parts]
    return [root / n for n in names]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", default="dropbridge-studio")
    parser.add_argument("--branch", default="main")
    parser.add_argument("--description", default="Windows 上接收 iPhone 隔空投送的图形界面控制台（DropBridge GUI）")
    args = parser.parse_args()

    token = os.environ.get("GH_TOKEN", "").strip()
    if not token:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        try:
            import gh_auth
            token = gh_auth.token()
        except SystemExit:
            token = ""
    if not token:
        print("missing GH_TOKEN (or run: python tools/gh_auth.py save <token>)")
        return 2

    root = Path(__file__).resolve().parent.parent
    os.chdir(root)

    status, user = api("/user", token)
    if status != 200:
        print("identity failed", status, user)
        return 1
    owner = user["login"]
    print("owner:", owner, flush=True)

    status, repo = api(f"/repos/{owner}/{args.repo}", token)
    if status == 404:
        status, repo = api("/user/repos", token, "POST", {
            "name": args.repo, "description": args.description,
            "private": False, "has_issues": True, "has_wiki": False, "auto_init": False,
        })
        print("created repo:", status, flush=True)
        if status not in (200, 201):
            print(json.dumps(repo, ensure_ascii=False)[:400])
            return 1

    # 空仓库不能直接建 blob（API 返回 409 Git Repository is empty），先用 Contents API 落一个种子提交
    status, existing = api(f"/repos/{owner}/{args.repo}/git/ref/heads/{args.branch}", token)
    if status in (404, 409):
        seed = base64.b64encode("# DropBridge Studio\n".encode()).decode("ascii")
        status, seeded = api(f"/repos/{owner}/{args.repo}/contents/README.md", token, "PUT", {
            "message": "chore: 初始化仓库",
            "content": seed,
            "branch": args.branch,
            "committer": {"name": AUTHOR_NAME, "email": AUTHOR_EMAIL},
            "author": {"name": AUTHOR_NAME, "email": AUTHOR_EMAIL},
        })
        print("seed commit:", status, flush=True)
        if status not in (200, 201):
            print(json.dumps(seeded, ensure_ascii=False)[:300])
            return 1

    files = tracked_files(root)
    files = [p for p in files if p.is_file() and ".git" not in p.parts]
    print("files to upload:", len(files), flush=True)

    entries = []
    for index, path in enumerate(files, start=1):
        content = path.read_bytes()
        status, blob = api(f"/repos/{owner}/{args.repo}/git/blobs", token, "POST", {
            "content": base64.b64encode(content).decode("ascii"),
            "encoding": "base64",
        })
        if status not in (200, 201):
            print("blob failed:", path, status, json.dumps(blob)[:200])
            return 1
        entries.append({"path": path.relative_to(root).as_posix(), "mode": "100644",
                        "type": "blob", "sha": blob["sha"]})
        if index % 10 == 0 or index == len(files):
            print(f"  blobs {index}/{len(files)}", flush=True)

    status, tree = api(f"/repos/{owner}/{args.repo}/git/trees", token, "POST",
                       {"tree": entries})
    print("tree:", status, flush=True)
    if status not in (200, 201):
        print(json.dumps(tree, ensure_ascii=False)[:400])
        return 1

    parents = []
    status, ref = api(f"/repos/{owner}/{args.repo}/git/ref/heads/{args.branch}", token)
    if status == 200:
        parents = [ref["object"]["sha"]]

    payload = {
        "message": MESSAGE,
        "tree": tree["sha"],
        "author": {"name": AUTHOR_NAME, "email": AUTHOR_EMAIL},
        "committer": {"name": AUTHOR_NAME, "email": AUTHOR_EMAIL},
    }
    if parents:
        payload["parents"] = parents
    status, commit = api(f"/repos/{owner}/{args.repo}/git/commits", token, "POST", payload)
    print("commit:", status, commit.get("sha", "")[:10], flush=True)
    if status not in (200, 201):
        print(json.dumps(commit, ensure_ascii=False)[:400])
        return 1

    if parents:
        status, res = api(f"/repos/{owner}/{args.repo}/git/refs/heads/{args.branch}", token, "PATCH",
                          {"sha": commit["sha"], "force": True})
    else:
        status, res = api(f"/repos/{owner}/{args.repo}/git/refs", token, "POST",
                          {"ref": f"refs/heads/{args.branch}", "sha": commit["sha"]})
    print("ref:", status, flush=True)
    if status not in (200, 201):
        print(json.dumps(res, ensure_ascii=False)[:400])
        return 1

    status, info = api(f"/repos/{owner}/{args.repo}", token)
    status2, contents = api(f"/repos/{owner}/{args.repo}/contents?ref={args.branch}", token)
    print("repo:", info.get("html_url"), "| default:", info.get("default_branch"))
    print("top-level entries:", len(contents) if isinstance(contents, list) else contents)
    return 0


if __name__ == "__main__":
    sys.exit(main())
