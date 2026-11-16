"""在 GitHub 上建仓库并把当前目录推上去（token 只从环境变量读，不写进 git config）。

用法：
    GH_TOKEN=xxx python tools/gh_publish.py [--repo dropbridge-studio] [--private]

做的事：
  1. GET /user 确认身份
  2. 仓库不存在就用 POST /user/repos 建一个
  3. 设置本地 commit 身份（Tomorin / noreply 邮箱）
  4. git add -A、commit（若还没提交）、push（token 通过 askpass 临时喂给 git，不落盘）
  5. 回读仓库信息和文件数做验证
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

API = "https://api.github.com"
AUTHOR_NAME = "Tomorin"
AUTHOR_EMAIL = "69080776+Accelerater-tech@users.noreply.github.com"
COMMIT_MESSAGE = """DropBridge Studio: 给 DropBridge 后端做一个图形化驾驶舱

按依赖顺序自动拉起 radio → bridge → netd → awdld → receiver，把后端日志
实时解析成指标，断线自动重启，并提供一键体检、自测接收、事件时间线、
诊断报告/抓包留证、托盘常驻与开机自启。

- app/   控制器（配置、链路管理、体检、自测、托盘、pywebview js_api、CLI）
- web/   界面（原生 HTML/CSS/JS，WebView2）
- tools/ CDP 截图、假发送端、探针、便携版打包
- 免安装版：tools/make_portable.py（自带 CPython 3.12）

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
        with urllib.request.urlopen(req, timeout=40) as resp:
            return resp.status, json.loads(resp.read().decode() or "{}")
    except urllib.error.HTTPError as err:
        body = err.read().decode(errors="replace")
        try:
            return err.code, json.loads(body)
        except ValueError:
            return err.code, {"raw": body[:500]}


def git(*args: str, env: dict | None = None, check: bool = True) -> subprocess.CompletedProcess:
    result = subprocess.run(["git", *args], capture_output=True, text=True, encoding="utf-8", errors="replace", env=env)
    if check and result.returncode != 0:
        print("git", " ".join(args), "failed:", (result.stderr or result.stdout)[:600])
        raise SystemExit(1)
    return result


def make_askpass(token: str) -> Path:
    """临时写一个 askpass 脚本，让 git 从它拿 token —— 命令里不出现 token，也不进 git config。"""
    if os.name == "nt":
        path = Path(tempfile.gettempdir()) / "dbstudio-askpass.cmd"
        path.write_text("@echo off\r\necho %DBSTUDIO_TOKEN%\r\n", encoding="ascii")
    else:
        path = Path(tempfile.gettempdir()) / "dbstudio-askpass.sh"
        path.write_text("#!/bin/sh\nprintf '%s\\n' \"$DBSTUDIO_TOKEN\"\n", encoding="utf-8")
        path.chmod(0o700)
    return path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", default="dropbridge-studio")
    parser.add_argument("--private", action="store_true")
    parser.add_argument("--description", default="Windows 上接收 iPhone 隔空投送的图形界面控制台（DropBridge GUI）")
    parser.add_argument("--no-push", action="store_true")
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
        print("identity failed:", status, user)
        return 1
    login = user["login"]
    print("identity:", login, user.get("name"))

    status, repo = api(f"/repos/{login}/{args.repo}", token)
    if status == 404:
        status, repo = api("/user/repos", token, "POST", {
            "name": args.repo,
            "description": args.description,
            "private": bool(args.private),
            "has_issues": True,
            "has_wiki": False,
            "auto_init": False,
        })
        print("create repo:", status)
        if status not in (200, 201):
            print(json.dumps(repo, ensure_ascii=False)[:500])
            return 1
    elif status != 200:
        print("repo lookup failed:", status, repo)
        return 1
    else:
        print("repo exists:", repo["html_url"])

    remote = f"https://github.com/{login}/{args.repo}.git"

    git("config", "user.name", AUTHOR_NAME)
    git("config", "user.email", AUTHOR_EMAIL)
    git("config", "core.autocrlf", "false")

    head = git("rev-parse", "--verify", "HEAD", check=False)
    if head.returncode != 0:
        git("add", "-A")
        git("-c", f"user.name={AUTHOR_NAME}", "-c", f"user.email={AUTHOR_EMAIL}",
            "commit", "-m", COMMIT_MESSAGE)
        print("first commit made")
    else:
        staged = git("status", "--porcelain").stdout.strip()
        if staged:
            git("add", "-A")
            git("commit", "-m", COMMIT_MESSAGE)
            print("commit made")

    git("branch", "-M", "main")
    remotes = git("remote").stdout.split()
    if "origin" in remotes:
        git("remote", "set-url", "origin", remote)
    else:
        git("remote", "add", "origin", remote)

    if args.no_push:
        print("skip push, remote =", remote)
        return 0

    askpass = make_askpass(token)
    env = dict(os.environ, DBSTUDIO_TOKEN=token, GIT_ASKPASS=str(askpass), GIT_TERMINAL_PROMPT="0")
    # 用户名走 https 里的 login，密码（token）由 askpass 提供
    auth_url = f"https://{login}@github.com/{login}/{args.repo}.git"
    push = subprocess.run(["git", "push", auth_url, "HEAD:main", "--force"], env=env,
                          capture_output=True, text=True, encoding="utf-8", errors="replace")
    askpass.unlink(missing_ok=True)
    print("push exit:", push.returncode)
    print((push.stdout or "")[-500:])
    print((push.stderr or "")[-800:])
    if push.returncode != 0:
        return 1

    status, info = api(f"/repos/{login}/{args.repo}", token)
    status2, tree = api(f"/repos/{login}/{args.repo}/contents", token)
    print("repo:", info.get("html_url"), "| default branch:", info.get("default_branch"))
    print("top-level entries:", len(tree) if isinstance(tree, list) else tree)
    return 0


if __name__ == "__main__":
    sys.exit(main())
