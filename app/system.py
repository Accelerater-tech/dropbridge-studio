"""Windows 集成：开机自启、打开目录、单实例提示。

自启用快捷方式而不是注册表，用户能在「启动」文件夹里直接看到并删掉，
这是最不容易被安全软件拦、也最讲道理的做法。
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

from . import config

SHORTCUT_NAME = "DropBridge Studio.lnk"


def _startup_dir() -> Path:
    appdata = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
    return Path(appdata) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"


def startup_shortcut() -> Path:
    return _startup_dir() / SHORTCUT_NAME


def autostart_enabled() -> bool:
    return startup_shortcut().is_file()


def _target() -> tuple[str, str, str]:
    """(可执行文件, 参数, 工作目录) —— 打包成 exe 与源码运行两种形态。"""
    if config.FROZEN:
        exe = str(config.EXE_PATH)
        return exe, "", str(config.EXE_PATH.parent)
    exe = Path(sys.executable)
    candidate = exe.with_name("pythonw.exe")
    python = str(candidate if candidate.is_file() else exe)
    return python, "-m app.main", str(config.HERE)


def set_autostart(enabled: bool) -> bool:
    """返回设置后的真实状态；失败不抛异常，交给界面提示。"""
    link = startup_shortcut()
    try:
        if not enabled:
            link.unlink(missing_ok=True)
            return False
        _startup_dir().mkdir(parents=True, exist_ok=True)
        import win32com.client  # 只有真正要写快捷方式时才需要

        shell = win32com.client.Dispatch("WScript.Shell")
        shortcut = shell.CreateShortCut(str(link))
        exe, arguments, workdir = _target()
        shortcut.TargetPath = exe
        shortcut.Arguments = arguments
        shortcut.WorkingDirectory = workdir
        icon = config.ASSET_DIR / "studio.ico"
        shortcut.IconLocation = str(icon) if icon.is_file() else ""
        shortcut.Description = "DropBridge Studio 后台接收隔空投送"
        shortcut.Save()
        return link.is_file()
    except Exception:
        return link.is_file()


def open_path(path: str | Path) -> None:
    target = Path(path)
    if target.is_file():
        os.startfile(str(target))  # noqa: S606 - 打开用户自己的文件
    else:
        target.mkdir(parents=True, exist_ok=True)
        os.startfile(str(target))
