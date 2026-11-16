"""把 DropBridge Studio 打成单文件 exe（PyInstaller onefile）。

为什么必须在 DSH 工作区外面构建：
  实测同一份 pythonnet / clr_loader 放在 DSH 工作区路径下会加载失败
  （Failed to resolve Python.Runtime.Loader.Initialize），换到普通目录就正常。
  打包产物同理，构建与试跑都放在 C:\\Users\\<user>\\dbstudio-build\\ 下。

用法：
  python tools/build_exe.py                 # 构建 + 试跑冒烟
  python tools/build_exe.py --no-smoke      # 只构建
产物：<构建目录>\\dist\\DropBridge Studio.exe
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
WORK = BUILD_ROOT / "exe-build"
DIST = BUILD_ROOT / "dist"

HIDDEN = [
    "webview.platforms.winforms",
    "webview.platforms.edgechromium",
    "webview.http",
    "bottle",
    "proxy_tools",
    "clr_loader",
    "pythonnet",
    "clr",
    "pythoncom",
    "pywintypes",
    "win32com",
    "win32com.client",
    "win32api",
    "win32con",
    "win32event",
    "win32gui",
    "pystray._win32",
    "PIL.Image",
    "PIL.ImageDraw",
    "psutil",
    "uuid",
    "plistlib",
    "ssl",
    "http.server",
    "zipfile",
]

# 一次性排除，别把测试/文档类的包拖进来
EXCLUDE = ["tkinter", "unittest", "pydoc_data", "test", "distutils.commands.check"]


def prepare_sources() -> Path:
    if WORK.exists():
        shutil.rmtree(WORK, ignore_errors=True)
    WORK.mkdir(parents=True)
    for name in ("app", "web", "assets"):
        shutil.copytree(ROOT / name, WORK / name, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    shutil.copy2(ROOT / "runstudio.py", WORK / "runstudio.py")
    return WORK


def build() -> Path:
    prepare_sources()
    DIST.mkdir(parents=True, exist_ok=True)
    icon = ROOT / "assets" / "studio.ico"
    args = [
        sys.executable, "-m", "PyInstaller",
        str(WORK / "runstudio.py"),
        "--name", "DropBridge Studio",
        "--onefile",
        "--noconsole",
        "--clean",
        "--noconfirm",
        "--distpath", str(DIST),
        "--workpath", str(BUILD_ROOT / "pyi-work"),
        "--specpath", str(BUILD_ROOT / "pyi-spec"),
        "--add-data", f"{WORK / 'web'};web",
        "--add-data", f"{WORK / 'assets'};assets",
        "--collect-all", "webview",
        "--collect-all", "clr_loader",
        "--collect-all", "pythonnet",
    ]
    for module in HIDDEN:
        args += ["--hidden-import", module]
    for module in EXCLUDE:
        args += ["--exclude-module", module]
    if icon.is_file():
        args += ["--icon", str(icon)]

    print("running:", " ".join(args[:6]), "...", flush=True)
    started = time.time()
    result = subprocess.run(args, cwd=BUILD_ROOT, capture_output=True, text=True, errors="replace")
    print(result.stdout[-3000:])
    print(result.stderr[-2000:])
    exe = DIST / "DropBridge Studio.exe"
    print("build seconds:", round(time.time() - started, 1), "| exists:", exe.is_file())
    if not exe.is_file():
        raise SystemExit("构建失败，看上面的 PyInstaller 输出")
    print("size MB:", round(exe.stat().st_size / 1_048_576, 1))
    return exe


def smoke(exe: Path) -> int:
    """调用 tools/smoke_exe.py：冷启动一次，等链路就绪。"""
    return subprocess.call([sys.executable, str(ROOT / "tools" / "smoke_exe.py"), str(exe)])


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-smoke", action="store_true")
    parser.add_argument("--smoke-only", action="store_true")
    args = parser.parse_args()
    exe = DIST / "DropBridge Studio.exe"
    if not args.smoke_only:
        exe = build()
    if not args.no_smoke:
        return smoke(exe)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
