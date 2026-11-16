"""生成的 exe 冒烟测试：冷启动 → 等五节点就绪 → 截图 → 关闭。

单独跑（不动构建）：
  python tools/smoke_exe.py "C:\\Users\\50174\\dbstudio-build\\dist\\DropBridge Studio.exe"

必须从 DSH 工作区外的目录启动 exe（.NET 在本工作区路径下加载 pythonnet 会失败）。
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import cdp  # noqa: E402


def wait_session(seconds: int = 90) -> cdp.Session | None:
    deadline = time.time() + seconds
    while time.time() < deadline:
        try:
            return cdp.Session()
        except Exception:  # noqa: BLE001 - WebView2 调试端口还没起来
            time.sleep(2)
    return None


def main() -> int:
    exe = Path(sys.argv[1]) if len(sys.argv) > 1 else Path.home() / "dbstudio-build" / "dist" / "DropBridge Studio.exe"
    if not exe.is_file():
        print("exe 不存在:", exe)
        return 2
    env = dict(os.environ)
    env["STUDIO_DEBUG"] = "1"
    proc = subprocess.Popen([str(exe)], env=env, cwd=str(exe.parent))
    print("launched pid", proc.pid, flush=True)
    session = wait_session()
    if session is None:
        print("CDP 连不上，窗口可能没起来")
        proc.terminate()
        return 1
    try:
        print("api methods:", session.eval("Object.keys(window.pywebview.api || {}).length"))
        deadline = time.time() + 150
        phase = ""
        while time.time() < deadline:
            try:
                raw = session.eval("window.pywebview.api.state().then(s => JSON.stringify({phase: s.phase, nodes: Object.keys(s.nodes || {})}))")
                if isinstance(raw, str) and raw.startswith("{"):
                    snap = json.loads(raw)
                    if snap.get("phase") != phase:
                        phase = snap.get("phase", "")
                        print("phase:", phase, "| nodes:", snap.get("nodes"))
            except Exception as error:  # noqa: BLE001
                print("state 读取失败:", type(error).__name__)
            if phase == "ready":
                out = ROOT / "data" / "exe-ready.png"
                session.shot(str(out))
                print("READY |", out)
                return 0
            time.sleep(3)
        print("超时，最后 phase:", phase)
        return 1
    finally:
        session.close()
        time.sleep(1)
        proc.terminate()


if __name__ == "__main__":
    raise SystemExit(main())
