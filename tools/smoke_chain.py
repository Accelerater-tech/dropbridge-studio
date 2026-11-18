"""整链冒烟：启动主程序 → 点「启动接收」→ 等五节点就绪 → 读发现层 → 截图诊断页。

  python tools/smoke_chain.py "C:\\Users\\50174\\dbstudio-build\\dist\\DropBridge Studio.exe"

必须从 DSH 工作区之外启动（工作区路径下 .NET 加载 pythonnet 会失败）。
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

WAIT_READY = 150


def wait_session(seconds: int = 90) -> "cdp.Session | None":
    deadline = time.time() + seconds
    while time.time() < deadline:
        try:
            return cdp.Session()
        except Exception:  # noqa: BLE001 - 调试端口还没起来
            time.sleep(2)
    return None


def read_state(session: "cdp.Session") -> dict:
    raw = session.eval(
        "window.pywebview.api.state().then(s => JSON.stringify({"
        "phase: s.phase, message: s.message,"
        "  children: (s.children || []).map(c => [c.name, c.ready]),"
        "  discovery: s.discovery || null,"
        "  settings: {close_to_tray: s.settings.close_to_tray, start_minimized: s.settings.start_minimized}"
        "}))"
    )
    if isinstance(raw, str) and raw.startswith("{"):
        return json.loads(raw)
    return {}


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
        print("CDP 连不上")
        proc.terminate()
        return 1
    try:
        print("api methods:", session.eval("Object.keys(window.pywebview.api || {}).length"))
        snap = read_state(session)
        print("settings:", snap.get("settings"))

        # 切到诊断页，方便截图看到「发现层」
        session.eval(
            "document.querySelector('.rail-btn[data-view=\"doctor\"]').click(); 'ok'"
        )
        print("start:", session.eval("window.pywebview.api.start().then(r => JSON.stringify(r))"))

        deadline = time.time() + WAIT_READY
        phase = ""
        while time.time() < deadline:
            snap = read_state(session)
            if snap.get("phase") != phase:
                phase = snap.get("phase", "")
                print("phase:", phase, "|", snap.get("message"), "|", snap.get("children"))
            if phase == "ready":
                break
            time.sleep(4)

        snap = read_state(session)
        print("discovery:", json.dumps(snap.get("discovery"), ensure_ascii=False))
        out = ROOT / "data" / "gui-discovery.png"
        out.parent.mkdir(parents=True, exist_ok=True)
        session.eval("document.querySelector('#discoveryTable').scrollIntoView({block: 'start'}); 'ok'")
        time.sleep(1)
        session.shot(str(out))
        print("shot:", out)
        if snap.get("phase") != "ready":
            print("没到 ready，最后 phase:", snap.get("phase"))
            return 1
        return 0
    finally:
        session.close()
        time.sleep(1)
        proc.terminate()


if __name__ == "__main__":
    raise SystemExit(main())
