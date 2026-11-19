"""把 installer/win_install.py + 单文件主程序打成 Setup.exe。

依赖 tools/build_exe.py 先产出 <家里>/dbstudio-build/dist/DropBridge Studio.exe。
产物：<家里>/dbstudio-build/dist/DropBridge-Studio-Setup-1.1.1.exe

用法：
  python tools/build_setup.py            # 构建 + 静默安装冒烟
  python tools/build_setup.py --no-smoke
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BUILD_ROOT = Path.home() / "dbstudio-build"
DIST = BUILD_ROOT / "dist"
WORK = BUILD_ROOT / "setup-build"
PAYLOAD = WORK / "payload"
VERSION = "1.1.1"


def prepare() -> None:
    exe = DIST / "DropBridge Studio.exe"
    if not exe.is_file():
        raise SystemExit("先跑 python tools/build_exe.py 生成主程序 exe")
    if WORK.exists():
        shutil.rmtree(WORK, ignore_errors=True)
    PAYLOAD.mkdir(parents=True)
    shutil.copy2(exe, PAYLOAD / "DropBridge Studio.exe")
    shutil.copy2(ROOT / "README.md", PAYLOAD / "README.md")
    shutil.copytree(ROOT / "assets", WORK / "assets")
    shutil.copy2(ROOT / "installer" / "win_install.py", WORK / "win_install.py")


def build() -> Path:
    prepare()
    name = f"DropBridge-Studio-Setup-{VERSION}"
    args = [
        sys.executable, "-m", "PyInstaller",
        str(WORK / "win_install.py"),
        "--name", name,
        "--onefile",
        "--noconsole",
        "--clean",
        "--noconfirm",
        "--distpath", str(DIST),
        "--workpath", str(BUILD_ROOT / "setup-pyi-work"),
        "--specpath", str(BUILD_ROOT / "setup-pyi-spec"),
        "--add-data", f"{PAYLOAD};payload",
        "--add-data", f"{WORK / 'assets'};assets",
        "--hidden-import", "win32com.client",
        "--hidden-import", "pythoncom",
        "--hidden-import", "pywintypes",
        "--exclude-module", "webview",
        "--exclude-module", "pythonnet",
        "--exclude-module", "clr_loader",
        "--icon", str(ROOT / "assets" / "studio.ico"),
    ]
    started = time.time()
    result = subprocess.run(args, cwd=BUILD_ROOT, capture_output=True, text=True, errors="replace")
    print(result.stdout[-1800:])
    print(result.stderr[-1200:])
    exe = DIST / f"{name}.exe"
    print("build seconds:", round(time.time() - started, 1), "| exists:", exe.is_file())
    if not exe.is_file():
        raise SystemExit("构建失败")
    print("size MB:", round(exe.stat().st_size / 1_048_576, 1))
    return exe


def smoke(setup: Path) -> int:
    """静默装到一个临时目录，检查文件/快捷方式/注册表，然后卸载。"""
    import winreg

    target = Path(os.environ["LOCALAPPDATA"]) / "Programs" / "DropBridge Studio Test"
    if target.exists():
        shutil.rmtree(target, ignore_errors=True)
    env = dict(os.environ)
    env["DBS_INSTALL_DIR"] = str(target)
    print("installing to", target, flush=True)
    result = subprocess.run([str(setup), "--silent", "--no-launch"], env=env, capture_output=True, text=True, errors="replace", timeout=300)
    print(result.stdout[-800:], result.stderr[-400:])
    exe = target / "DropBridge Studio.exe"
    print("main exe:", exe.is_file(), exe.stat().st_size if exe.is_file() else 0)
    print("uninstall.cmd:", (target / "uninstall.cmd").is_file())
    desktop = Path(os.environ["USERPROFILE"]) / "Desktop" / "DropBridge Studio.lnk"
    print("desktop shortcut:", desktop.is_file())
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Uninstall\DropBridgeStudio") as key:
            print("registry DisplayName:", winreg.QueryValueEx(key, "DisplayName")[0])
    except FileNotFoundError:
        print("registry: MISSING")
    # 卸载
    subprocess.run(["cmd.exe", "/c", str(target / "uninstall.cmd")], capture_output=True, timeout=120)
    time.sleep(1.5)
    print("after uninstall dir exists:", target.exists(), "| desktop link:", desktop.exists())
    return 0 if not target.exists() else 1


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-smoke", action="store_true")
    args = parser.parse_args()
    setup = build()
    if not args.no_smoke:
        return smoke(setup)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
