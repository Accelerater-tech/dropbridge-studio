"""做一个免安装、自带 Python 运行时的分发目录。

PyInstaller 打出来的 exe 里 pythonnet 解析 .NET 运行时会失败（pywebview 在 Windows
上要靠 pythonnet 驱动 WebView2），所以改走「整个 Python 一起带走」的方案：
把本机的 CPython 和要用的 site-packages 复制进 dist-portable，配一个启动脚本。

用法：python tools/make_portable.py
产物：dist-portable/DropBridge Studio/  +  启动 DropBridge Studio.cmd
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# 默认放到桌面：.NET CLR 在 DSH 工作区路径下加载程序集会失败（实测），
# 而且用户双击的也应该是桌面上这个。
DEFAULT_OUT = Path.home() / "Desktop" / "DropBridge Studio"
OUT = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else DEFAULT_OUT

PY_HOME = Path(sys.base_prefix)                     # ...\Python312
PY_LIB = PY_HOME / "Lib"
SITE = Path(sys.executable).parent / "Lib" / "site-packages"

# 只带运行期真正需要的包（其余全是开发/打包工具）
WANTED_PKGS = [
    "webview", "bottle", "proxy_tools", "typing_extensions", "pythonnet", "clr_loader",
    "cffi", "pycparser", "pystray", "PIL", "psutil", "win32com", "win32", "win32api",
    "win32con", "win32file", "win32gui", "win32process", "win32event", "win32security",
    "win32clipboard", "win32ui", "pywintypes", "pythonwin", "winpty", "comtypes",
    "pywin32_system32", "pkg_resources", "setuptools", "_distutils_hack",
]
WANTED_FILES = ["distutils-precedence.pth", "pywin32.pth"]

SKIP_DIRS = {"__pycache__", "tests", "test", "doc", "docs", "examples"}


def copy_tree(src: Path, dst: Path) -> None:
    shutil.copytree(
        src, dst, dirs_exist_ok=True,
        ignore=shutil.ignore_patterns(*SKIP_DIRS, "*.pyc"),
    )


def main() -> int:
    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True)

    # 1) 解释器本体
    for name in ("python.exe", "pythonw.exe", "python3.dll", "python312.dll", "vcruntime140.dll",
                 "vcruntime140_1.dll"):
        src = PY_HOME / name
        if src.is_file():
            shutil.copy2(src, OUT / name)

    # 2) 标准库 + DLLs（_socket 等扩展模块都在 DLLs 里）
    print("copying stdlib ...")
    copy_tree(PY_LIB, OUT / "Lib")
    copy_tree(PY_HOME / "DLLs", OUT / "DLLs")

    # 3) 第三方库
    print("copying site-packages ...")
    target_site = OUT / "Lib" / "site-packages"
    target_site.mkdir(parents=True, exist_ok=True)
    for name in WANTED_PKGS:
        src = SITE / name
        if src.is_dir():
            copy_tree(src, target_site / name)
        elif src.is_file():
            shutil.copy2(src, target_site / name)
    for name in WANTED_FILES:
        src = SITE / name
        if src.is_file():
            shutil.copy2(src, target_site / name)

    # 4) 应用代码
    print("copying studio ...")
    copy_tree(ROOT / "app", OUT / "app")
    copy_tree(ROOT / "web", OUT / "web")
    copy_tree(ROOT / "assets", OUT / "assets")
    shutil.copy2(ROOT / "runstudio.py", OUT / "runstudio.py")
    for name in ("README.md",):
        src = ROOT / name
        if src.is_file():
            shutil.copy2(src, OUT / name)

    # 5) 启动脚本（纯 ASCII，避免 cmd 按 GBK 解析中文出错）
    launcher = OUT / "\u542f\u52a8 DropBridge Studio.cmd"
    launcher.write_text(
        "@echo off\r\n"
        "rem Start DropBridge Studio with the bundled Python runtime.\r\n"
        "setlocal\r\n"
        "cd /d \"%~dp0\"\r\n"
        "if not exist \"%~dp0pythonw.exe\" (\r\n"
        "  echo pythonw.exe is missing - the package is incomplete.\r\n"
        "  pause\r\n"
        "  exit /b 1\r\n"
        ")\r\n"
        "start \"\" \"%~dp0pythonw.exe\" \"%~dp0runstudio.py\"\r\n"
        "exit /b 0\r\n",
        encoding="ascii",
    )
    # 英文名启动脚本：有些解压工具不认 zip 里的 UTF-8 中文名，留个兜底
    launcher_en = ROOT / "tools" / "launcher_en.cmd"
    if launcher_en.is_file():
        shutil.copy2(launcher_en, OUT / "Start DropBridge Studio.cmd")
    print("done ->", OUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
