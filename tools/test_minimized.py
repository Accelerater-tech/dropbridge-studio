"""启动最小化验证：直接改 settings.json → 启动 → 看窗口有没有弹出来。

  python tools/test_minimized.py "C:\\Users\\50174\\dbstudio-build\\dist\\DropBridge Studio.exe"

备注：PyInstaller onefile 有父子两个进程，只 terminate 父进程会留下子进程，所以统一 kill_all()。
"""
from __future__ import annotations

import ctypes
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import psutil

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import cdp  # noqa: E402

TITLE = "DropBridge Studio"
SETTINGS = Path(r"C:\Users\50174\Desktop\DropBridge\data\studio\settings.json")
user32 = ctypes.windll.user32


def kill_all() -> None:
    for item in psutil.process_iter():
        if "DropBridge" in (item.name() or ""):
            try:
                item.kill()
            except Exception:  # noqa: BLE001
                pass
    time.sleep(1.5)


def patch_settings(**values) -> dict:
    data = json.loads(SETTINGS.read_text(encoding="utf-8"))
    data.update(values)
    SETTINGS.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    return {key: data[key] for key in values}


def find_window() -> int:
    return int(user32.FindWindowW(None, TITLE) or 0)


def wait_session(seconds: int = 90) -> "cdp.Session | None":
    deadline = time.time() + seconds
    while time.time() < deadline:
        try:
            return cdp.Session()
        except Exception:  # noqa: BLE001
            time.sleep(2)
    return None


def main() -> int:
    exe = Path(sys.argv[1]) if len(sys.argv) > 1 else Path.home() / "dbstudio-build" / "dist" / "DropBridge Studio.exe"
    if not exe.is_file():
        print("exe 不存在:", exe)
        return 2
    env = dict(os.environ)
    env["STUDIO_DEBUG"] = "1"
    failures: list[str] = []
    kill_all()

    try:
        # ---- 第一阶段：正常启动，关掉 start_minimized，顺便截一张设置页 ----
        print("settings:", patch_settings(start_minimized=False, close_to_tray=True))
        proc = subprocess.Popen([str(exe)], env=env, cwd=str(exe.parent))
        session = wait_session()
        if session is None:
            print("第一阶段 CDP 连不上")
            return 1
        try:
            time.sleep(2)
            session.eval("document.querySelector('.rail-btn[data-view=\"settings\"]').click(); 'ok'")
            time.sleep(1.5)
            out = ROOT / "data" / "gui-settings-tray.png"
            session.shot(str(out))
            print("shot:", out)
            print("state:", session.eval(
                "window.pywebview.api.state().then(s => JSON.stringify({"
                "close_to_tray: s.settings.close_to_tray, tray: s.tray || null}))"))
        finally:
            session.close()
        proc.terminate()
        kill_all()

        # ---- 第二阶段：start_minimized=true，窗口应该根本不出现 ----
        print("settings:", patch_settings(start_minimized=True))
        proc = subprocess.Popen([str(exe)], env=env, cwd=str(exe.parent))
        time.sleep(10)
        handle = find_window()
        shown = bool(handle and user32.IsWindowVisible(handle))
        running = any("DropBridge" in (item.name() or "") for item in psutil.process_iter())
        print("second launch | hwnd:", handle, "| visible:", shown, "| running:", running)
        if shown:
            failures.append("start_minimized 打开后窗口还是弹出来了")
        if not running:
            failures.append("最小化启动时进程没起来")
        proc.terminate()
        kill_all()
    finally:
        # 恢复现场：默认还是不自动隐藏，免得用户下次双击看不到窗口
        print("restore:", patch_settings(start_minimized=False))

    if failures:
        for item in failures:
            print("FAIL:", item)
        return 1
    print("OK: 启动后最小化只在托盘里待着")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
