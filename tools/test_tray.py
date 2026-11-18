"""托盘常驻冒烟：启动 → 链路就绪 → 关主窗口 → 断言进程/s链路都还在。

  python tools/test_tray.py "C:\\Users\\50174\\dbstudio-build\\dist\\DropBridge Studio.exe"

验证的是用户真正在意的行为：点 X 之后程序不退出、接收链路不停、托盘还在。
"""
from __future__ import annotations

import ctypes
import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import cdp  # noqa: E402

TITLE = "DropBridge Studio"
WM_CLOSE = 0x0010
user32 = ctypes.windll.user32


def wait_session(seconds: int = 90) -> "cdp.Session | None":
    deadline = time.time() + seconds
    while time.time() < deadline:
        try:
            return cdp.Session()
        except Exception:  # noqa: BLE001 - 调试端口还没起来
            time.sleep(2)
    return None


def find_window() -> int:
    return int(user32.FindWindowW(None, TITLE) or 0)


def visible(handle: int) -> bool:
    return bool(handle) and bool(user32.IsWindowVisible(handle))


def window_pid(handle: int) -> int:
    pid = ctypes.c_ulong()
    user32.GetWindowThreadProcessId(ctypes.c_void_p(handle), ctypes.byref(pid))
    return int(pid.value)


def alive_pid(pid: int) -> bool:
    import psutil
    return bool(pid) and psutil.pid_exists(pid)


def read_state(session: "cdp.Session") -> dict:
    raw = session.eval(
        "window.pywebview.api.state().then(s => JSON.stringify({"
        "phase: s.phase, tray: s.tray || null,"
        "  ready: (s.children || []).filter(c => c.ready).length"
        "}))"
    )
    return json.loads(raw) if isinstance(raw, str) and raw.startswith("{") else {}


def main() -> int:
    exe = Path(sys.argv[1]) if len(sys.argv) > 1 else Path.home() / "dbstudio-build" / "dist" / "DropBridge Studio.exe"
    if not exe.is_file():
        print("exe 不存在:", exe)
        return 2
    env = dict(os.environ)
    env["STUDIO_DEBUG"] = "1"
    proc = subprocess.Popen([str(exe)], env=env, cwd=str(exe.parent))
    session = wait_session()
    if session is None:
        print("CDP 连不上")
        proc.terminate()
        return 1

    failures: list[str] = []
    try:
        handle = 0
        deadline = time.time() + 20
        while time.time() < deadline and not handle:
            handle = find_window()
            if not handle:
                time.sleep(1)
        if not handle:
            failures.append("找不到主窗口")
        else:
            print("window handle:", handle, "visible:", visible(handle))

        session.eval("window.pywebview.api.start().then(r => JSON.stringify(r))")
        wait = time.time() + 180
        snap: dict = {}
        while time.time() < wait:
            snap = read_state(session)
            if snap.get("phase") == "ready":
                break
            time.sleep(4)
        print("phase:", snap.get("phase"), "| ready nodes:", snap.get("ready"), "| tray:", snap.get("tray"))
        if snap.get("phase") != "ready":
            failures.append("链路没到 ready")
        if not (snap.get("tray") or {}).get("running"):
            failures.append("托盘图标没起来")

        # 点「关闭窗口」= 发 WM_CLOSE，应该只是藏起来
        if handle:
            owner = window_pid(handle)
            print("window owner pid:", owner)
            user32.PostMessageW(handle, WM_CLOSE, 0, 0)
            time.sleep(4)
            handle = find_window() or handle
            print("after close | owner alive:", alive_pid(owner),
                  "| window visible:", visible(handle))
            if not alive_pid(owner):
                failures.append("关窗口后进程退出了")
            if visible(handle):
                failures.append("关窗口后窗口还显示着")
            snap = read_state(session)
            print("after close | phase:", snap.get("phase"), "| tray:", snap.get("tray"))
            if snap.get("phase") != "ready":
                failures.append("关窗口后链路断了")
            if not (snap.get("tray") or {}).get("running"):
                failures.append("关窗口后托盘没了")

        # 再点一次图标（等价于再启动一次）：主窗口应该自己回来
        if handle:
            second = subprocess.Popen([str(exe)], env=env, cwd=str(exe.parent))
            try:
                second.wait(timeout=30)
            except subprocess.TimeoutExpired:
                second.terminate()
            time.sleep(3)
            print("second launch | window visible:", visible(handle))
            if not visible(handle):
                failures.append("再次启动没把窗口叫回来")
            handle = find_window() or handle
            if not alive_pid(owner if handle else 0):
                failures.append("第二次启动把主进程弄没了")

        out = ROOT / "data" / "tray-hidden.json"
        out.write_text(json.dumps(snap, ensure_ascii=False, indent=2), encoding="utf-8")
    finally:
        session.close()
        time.sleep(1)
        proc.terminate()

    if failures:
        for item in failures:
            print("FAIL:", item)
        return 1
    print("OK: 关窗口后进程/链路/托盘都在")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
