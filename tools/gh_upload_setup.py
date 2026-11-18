"""把 Setup.exe 作为 Release 资源上传，并更新 Release 说明。

用法：GH_TOKEN=xxx python tools/gh_upload_setup.py [--replace]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
from gh_release import OWNER, REPO, api, upload_asset  # noqa: E402

TAG = "v1.1.0"
BODY = """## 两种装法，任选一个

### 1. 安装版（推荐）

下载 `DropBridge-Studio-Setup-1.1.0.exe`（约 33 MB），双击安装：

- **安装位置可以自己改**（默认 `%LOCALAPPDATA%\\Programs\\DropBridge Studio`，也能指到 `D:\\Apps\\...`）
- 自动建桌面 + 开始菜单快捷方式
- 控制面板「应用和功能」里能看到，能正常卸载
- 自带 Python 运行时，不需要本机装过 Python

### 2. 免安装版

下载 `DropBridge-Studio-portable.zip`（约 67 MB），解压到任意普通目录，
双击 `启动 DropBridge Studio.cmd`（或英文名 `Start DropBridge Studio.cmd`）。

## 使用前提

- RTL8821CU USB 无线网卡（USB ID `0bda:c820`）+ WinUSB 驱动
  （Studio 的「诊断 → 修复驱动」可以一键装，需要管理员权限）
- 首次启动等 40~70 秒：网卡要下固件、AWDL 五级链路要逐级握手，这是正常的
- ⚠️ 别放在 DSH 工作区这种特殊路径下运行，.NET 会加载不了 `Python.Runtime.dll`

界面、功能两种装法完全一致。
"""


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--file", default=str(Path.home() / "dbstudio-build" / "dist" / "DropBridge-Studio-Setup-1.1.0.exe"))
    parser.add_argument("--replace", action="store_true")
    args = parser.parse_args()

    token = os.environ.get("GH_TOKEN", "").strip()
    if not token:
        import gh_auth

        token = gh_auth.token()

    setup = Path(args.file)
    if not setup.is_file():
        raise SystemExit(f"找不到 {setup}")
    print("setup size MB:", round(setup.stat().st_size / 1_048_576, 1))

    status, release = api(f"/repos/{OWNER}/{REPO}/releases/tags/{TAG}", token)
    if status != 200:
        raise SystemExit(f"release 不存在: {status}")

    for asset in release.get("assets", []):
        if asset["name"] == setup.name:
            if not args.replace:
                print("asset 已存在:", asset["browser_download_url"])
                return 0
            import urllib.request

            req = urllib.request.Request(
                f"https://api.github.com/repos/{OWNER}/{REPO}/releases/assets/{asset['id']}", method="DELETE"
            )
            req.add_header("Authorization", f"Bearer {token}")
            req.add_header("User-Agent", "dbstudio")
            with urllib.request.urlopen(req, timeout=60) as resp:
                print("replaced old asset:", resp.status)

    status, asset = upload_asset(token, release["id"], setup)
    print("upload:", status, round(asset.get("size", 0) / 1_048_576, 1), "MB", asset.get("browser_download_url"))

    status, updated = api(f"/repos/{OWNER}/{REPO}/releases/{release['id']}", token, "PATCH", {"body": BODY})
    print("release body updated:", status)

    status, check = api(f"/repos/{OWNER}/{REPO}/releases/tags/{TAG}", token)
    for a in check.get("assets", []):
        print("asset:", a["name"], round(a["size"] / 1_048_576, 1), "MB", "|", a["browser_download_url"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
