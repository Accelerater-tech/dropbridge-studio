"""把桌面上的免安装版打成 zip，作为 GitHub Release 资源上传。

为什么不用 git 提交：185 MB、上万个文件，Git Data API 要上千次请求；
Release 资源单文件上限 2 GB，正合适。

用法：GH_TOKEN=xxx python tools/gh_release.py [--dir "C:\\Users\\...\\DropBridge Studio"] [--tag v1.1.0]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path

API = "https://api.github.com"
UPLOADS = "https://uploads.github.com"
OWNER = "Accelerater-tech"
REPO = "dropbridge-studio"


def api(path: str, token: str, method: str = "GET", payload: dict | None = None) -> tuple[int, dict]:
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(API + path, data=data, method=method)
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("User-Agent", "dbstudio")
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


def build_zip(source: Path, target: Path) -> None:
    if target.exists():
        target.unlink()
    files = sorted(p for p in source.rglob("*") if p.is_file())
    print(f"zipping {len(files)} files from {source}", flush=True)
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for index, path in enumerate(files, start=1):
            arc = Path(source.name) / path.relative_to(source)
            zf.write(path, arc.as_posix())
            if index % 2000 == 0:
                print(f"  {index}/{len(files)}", flush=True)
    print("zip size:", round(target.stat().st_size / 1_048_576, 1), "MB", flush=True)


def upload_asset(token: str, release_id: int, path: Path) -> tuple[int, dict]:
    url = f"{UPLOADS}/repos/{OWNER}/{REPO}/releases/{release_id}/assets?name={urllib.parse.quote(path.name)}"
    req = urllib.request.Request(url, data=path.read_bytes(), method="POST")
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("Content-Type", "application/zip")
    req.add_header("Content-Length", str(path.stat().st_size))
    req.add_header("User-Agent", "dbstudio")
    req.add_header("X-GitHub-Api-Version", "2022-11-28")
    started = time.time()
    with urllib.request.urlopen(req, timeout=1800) as resp:
        print("uploaded in", round(time.time() - started, 1), "s", flush=True)
        return resp.status, json.loads(resp.read().decode())


BODY = """## 免安装版（Windows x64）

下载 `DropBridge-Studio-portable.zip`，解压到**任意普通目录**（例如桌面、`D:\\Apps\\`），
双击 `DropBridge Studio\\启动 DropBridge Studio.cmd` 即可。

- 自带 CPython 3.12 和全部依赖，**不需要本机装过 Python**
- 数据写在后端目录 `data\\studio\\` 下（设置、时间线、捕获包）
- 需要 RTL8821CU USB 网卡 + WinUSB 驱动（Studio 的「诊断 → 修复驱动」可一键装）
- ⚠️ 别放在 DSH 工作区这种特殊路径下运行，.NET 会加载不了 `Python.Runtime.dll`

界面、功能与源码版完全一致。
"""


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dir", default=str(Path.home() / "Desktop" / "DropBridge Studio"))
    parser.add_argument("--tag", default="v1.1.1")
    parser.add_argument("--out", default=str(Path.home() / "dbstudio-build" / "DropBridge-Studio-portable.zip"))
    parser.add_argument("--skip-zip", action="store_true")
    parser.add_argument("--replace", action="store_true", help="同名资源已存在时删掉重传")
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

    source = Path(args.dir)
    target = Path(args.out)
    target.parent.mkdir(parents=True, exist_ok=True)
    if not args.skip_zip:
        build_zip(source, target)

    status, release = api(f"/repos/{OWNER}/{REPO}/releases/tags/{args.tag}", token)
    if status == 200:
        print("release exists:", release["html_url"], flush=True)
    else:
        status, release = api(f"/repos/{OWNER}/{REPO}/releases", token, "POST", {
            "tag_name": args.tag,
            "target_commitish": "main",
            "name": "DropBridge Studio " + args.tag + " 免安装版",
            "body": BODY,
            "draft": False,
            "prerelease": False,
        })
        print("create release:", status, flush=True)
        if status not in (200, 201):
            print(json.dumps(release, ensure_ascii=False)[:400])
            return 1

    release_id = release["id"]
    for asset in release.get("assets", []):
        if asset["name"] == target.name:
            if not args.replace:
                print("asset exists, size:", asset["size"], "->", asset["browser_download_url"], flush=True)
                return 0
            req = urllib.request.Request(
                f"{API}/repos/{OWNER}/{REPO}/releases/assets/{asset['id']}", method="DELETE")
            req.add_header("Authorization", f"Bearer {token}")
            req.add_header("User-Agent", "dbstudio")
            with urllib.request.urlopen(req, timeout=60) as resp:
                print("replaced: removed old asset", resp.status, flush=True)

    status, asset = upload_asset(token, release_id, target)
    print("upload:", status, asset.get("state"), asset.get("browser_download_url"), flush=True)

    status, check = api(f"/repos/{OWNER}/{REPO}/releases/tags/{args.tag}", token)
    for a in check.get("assets", []):
        print("asset:", a["name"], round(a["size"] / 1_048_576, 1), "MB", "|", a["browser_download_url"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
