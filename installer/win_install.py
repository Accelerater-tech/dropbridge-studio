"""DropBridge Studio 安装器（打成单文件 Setup.exe）。

做的事：
  1. 把内置的 DropBridge Studio.exe 复制到用户选择的位置（默认 %LOCALAPPDATA%\\Programs\\DropBridge Studio）
  2. 建桌面 + 开始菜单快捷方式
  3. 写 HKCU 卸载项（应用和功能里能看到、能卸载）
  4. 可选：装完立刻启动

命令行：
  Setup.exe                                  打开图形界面（可改安装位置）
  Setup.exe --silent [--dir D:\\Apps\\...]   静默安装
  Setup.exe --silent --no-launch             静默安装但不启动
环境变量：
  DBS_INSTALL_DIR   覆盖默认安装目录（--dir 优先）
  DBS_PAYLOAD_DIR   内置主程序所在目录（测试用）
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

APP_NAME = "DropBridge Studio"
APP_EXE = "DropBridge Studio.exe"
APP_ID = "DropBridgeStudio"
VERSION = "1.0.0"
PUBLISHER = "Tomorin"

# 卸载脚本保持纯 ASCII：cmd 控制台代码页会把中文压成乱码，甚至影响命令解析
UNINSTALL_TEMPLATE = (
    "@echo off\r\n"
    "rem DropBridge Studio uninstaller\r\n"
    "echo Removing {app} ...\r\n"
    "taskkill /f /im \"{exe}\" >nul 2>&1\r\n"
    "reg delete \"HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\{app_id}\" /f >nul 2>&1\r\n"
    "del /f /q \"%USERPROFILE%\\Desktop\\{app}.lnk\" >nul 2>&1\r\n"
    "del /f /q \"%APPDATA%\\Microsoft\\Windows\\Start Menu\\Programs\\{app}.lnk\" >nul 2>&1\r\n"
    "cd /d \"%TEMP%\"\r\n"
    "rmdir /s /q \"{target}\"\r\n"
    "if exist \"{target}\" (\r\n"
    "  echo Some files are still in use. Close {app} and run this file again.\r\n"
    "  pause\r\n"
    "  exit /b 1\r\n"
    ")\r\n"
    "echo Done. {app} has been removed.\r\n"
)


def payload_dir() -> Path:
    override = os.environ.get("DBS_PAYLOAD_DIR", "").strip()
    if override:
        return Path(override)
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return base / "payload"


def asset_path(name: str) -> Path:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    for candidate in (base / "assets" / name, base / name, Path(__file__).resolve().parent / "assets" / name):
        if candidate.is_file():
            return candidate
    return base / name


def default_target() -> Path:
    override = os.environ.get("DBS_INSTALL_DIR", "").strip()
    if override:
        return Path(override)
    local = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    return Path(local) / "Programs" / APP_NAME


def kill_running() -> None:
    try:
        subprocess.run(["taskkill", "/f", "/im", APP_EXE], capture_output=True, timeout=20)
        time.sleep(0.8)
    except (OSError, subprocess.SubprocessError):
        pass


def make_shortcut(path: Path, target: Path) -> bool:
    try:
        import win32com.client
    except ImportError:
        return False
    try:
        shell = win32com.client.Dispatch("WScript.Shell")
        link = shell.CreateShortCut(str(path))
        link.TargetPath = str(target)
        link.WorkingDirectory = str(target.parent)
        link.IconLocation = f"{target},0"
        link.Description = "接收 iPhone 隔空投送的 Windows 控制台"
        link.Save()
        return True
    except Exception:  # noqa: BLE001 - 快捷方式失败不该让安装失败
        return False


def write_registry(target: Path) -> None:
    try:
        import winreg
    except ImportError:  # pragma: no cover
        return
    key_path = rf"Software\Microsoft\Windows\CurrentVersion\Uninstall\{APP_ID}"
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, key_path) as key:
        winreg.SetValueEx(key, "DisplayName", 0, winreg.REG_SZ, APP_NAME)
        winreg.SetValueEx(key, "DisplayVersion", 0, winreg.REG_SZ, VERSION)
        winreg.SetValueEx(key, "Publisher", 0, winreg.REG_SZ, PUBLISHER)
        winreg.SetValueEx(key, "DisplayIcon", 0, winreg.REG_SZ, str(target))
        winreg.SetValueEx(key, "InstallLocation", 0, winreg.REG_SZ, str(target))
        winreg.SetValueEx(key, "NoModify", 0, winreg.REG_DWORD, 1)
        winreg.SetValueEx(key, "NoRepair", 0, winreg.REG_DWORD, 1)
        winreg.SetValueEx(key, "EstimatedSize", 0, winreg.REG_DWORD, 24_000)
        winreg.SetValueEx(key, "UninstallString", 0, winreg.REG_SZ, str(target / "uninstall.cmd"))


def install(target: Path, progress=None) -> Path:
    payload = payload_dir()
    source = payload / APP_EXE
    if not source.is_file():
        raise SystemExit(f"setup incomplete: {source} not found")

    steps = ["准备目录", "复制主程序", "写卸载信息", "创建快捷方式"]
    for index, label in enumerate(steps):
        if progress:
            progress(index, len(steps), label)
        if label == "准备目录":
            kill_running()
            target.mkdir(parents=True, exist_ok=True)
        elif label == "复制主程序":
            shutil.copy2(source, target / APP_EXE)
            readme = payload / "README.md"
            if readme.is_file():
                shutil.copy2(readme, target / "README.md")
            (target / "uninstall.cmd").write_text(
                UNINSTALL_TEMPLATE.format(exe=APP_EXE, app=APP_NAME, app_id=APP_ID, target=target),
                encoding="ascii",
            )
        elif label == "写卸载信息":
            write_registry(target)
        elif label == "创建快捷方式":
            desktop = Path(os.environ.get("USERPROFILE", str(Path.home()))) / "Desktop"
            start_menu = Path(os.environ.get("APPDATA", "")) / "Microsoft" / "Windows" / "Start Menu" / "Programs"
            make_shortcut(desktop / f"{APP_NAME}.lnk", target / APP_EXE)
            if start_menu.is_dir():
                make_shortcut(start_menu / f"{APP_NAME}.lnk", target / APP_EXE)
    if progress:
        progress(len(steps), len(steps), "完成")
    return target / APP_EXE


def run_gui() -> int:
    import threading
    import tkinter as tk
    from tkinter import ttk

    try:  # 高 DPI 屏上不糊
        import ctypes

        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:  # noqa: BLE001
        pass

    root = tk.Tk()
    root.title(f"{APP_NAME} 安装程序")
    root.minsize(640, 340)
    root.resizable(False, False)
    try:
        root.iconbitmap(str(asset_path("studio.ico")))
    except Exception:  # noqa: BLE001 - 没图标也照装
        pass

    style = ttk.Style(root)
    try:
        style.theme_use("vista")
    except tk.TclError:
        pass
    root.option_add("*Font", ("Segoe UI", 10))

    outer = ttk.Frame(root, padding=(24, 20, 24, 18))
    outer.pack(fill="both", expand=True)

    buttons = ttk.Frame(outer)
    buttons.pack(side="bottom", fill="x", pady=(18, 0))

    ttk.Label(outer, text=APP_NAME, font=("Segoe UI", 18, "bold")).pack(anchor="w")
    ttk.Label(
        outer,
        text="把 Windows 变成 iPhone 隔空投送的接收端。\n装好后桌面就有图标，双击即可启动。",
        justify="left",
        foreground="#4a4a4a",
    ).pack(anchor="w", pady=(6, 14))

    ttk.Label(outer, text="安装位置（可以改，例如 D:\\Apps\\DropBridge Studio）", foreground="#6b6b6b").pack(anchor="w")
    path_row = ttk.Frame(outer)
    path_row.pack(fill="x", pady=(4, 14))
    target_var = tk.StringVar(value=str(default_target()))
    target_entry = ttk.Entry(path_row, textvariable=target_var)
    target_entry.pack(side="left", fill="x", expand=True, ipady=3)

    def browse() -> None:
        from tkinter import filedialog

        current = Path(target_var.get())
        start = current.parent if current.parent.exists() else Path.home()
        chosen = filedialog.askdirectory(title="选择安装位置", initialdir=str(start))
        if chosen:
            target_var.set(str(Path(chosen) / APP_NAME))

    ttk.Button(path_row, text="浏览…", width=7, command=browse).pack(side="left", padx=(8, 0))

    bar = ttk.Progressbar(outer, mode="determinate", maximum=100)
    bar.pack(fill="x")
    status = ttk.Label(outer, text="准备就绪", foreground="#333333")
    status.pack(anchor="w", pady=(6, 0))

    launch = tk.BooleanVar(value=True)
    ttk.Checkbutton(outer, text="安装完成后立即启动", variable=launch).pack(anchor="w", pady=(14, 0))

    def on_progress(done: int, total: int, label: str) -> None:
        bar["value"] = int(done / total * 100)
        status.config(text=label)

    def do_install() -> None:
        install_button.config(state="disabled", text="安装中…")
        cancel_button.config(state="disabled")
        target_entry.config(state="disabled")
        chosen = target_var.get().strip()
        target = Path(chosen) if chosen else default_target()

        def worker() -> None:
            try:
                exe = install(target, progress=lambda d, t, label: root.after(0, on_progress, d, t, label))
            except Exception as error:  # noqa: BLE001
                message = f"安装失败：{error}"
                root.after(0, lambda: status.config(text=message))
                root.after(0, lambda: install_button.config(state="normal", text="重试"))
                root.after(0, lambda: cancel_button.config(state="normal"))
                root.after(0, lambda: target_entry.config(state="normal"))
                return
            done = f"安装完成，位置：{target}"
            root.after(0, lambda: status.config(text=done))
            root.after(0, lambda: install_button.config(state="normal", text="完成"))
            if launch.get():
                subprocess.Popen([str(exe)], cwd=str(exe.parent))

        threading.Thread(target=worker, daemon=True).start()

    install_button = ttk.Button(buttons, text="开始安装", width=12, command=do_install)
    install_button.pack(side="right")
    cancel_button = ttk.Button(buttons, text="取消", width=8, command=root.destroy)
    cancel_button.pack(side="right", padx=(0, 10))

    root.update_idletasks()
    width = max(root.winfo_reqwidth(), 640)
    height = root.winfo_reqheight()
    x = max((root.winfo_screenwidth() - width) // 2, 0)
    y = max((root.winfo_screenheight() - height) // 3, 0)
    root.geometry(f"{width}x{height}+{x}+{y}")

    root.mainloop()
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--silent", action="store_true")
    parser.add_argument("--no-launch", action="store_true")
    parser.add_argument("--dir", default="")
    args = parser.parse_args()

    if args.silent:
        target = Path(args.dir) if args.dir else default_target()
        exe = install(target, progress=lambda d, t, label: print(f"[{d}/{t}] {label}", flush=True))
        print("installed:", exe)
        if not args.no_launch:
            subprocess.Popen([str(exe)], cwd=str(exe.parent))
            print("launched")
        return 0

    if args.dir:
        os.environ["DBS_INSTALL_DIR"] = args.dir
    return run_gui()


if __name__ == "__main__":
    raise SystemExit(main())
