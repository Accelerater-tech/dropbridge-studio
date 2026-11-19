"""临时：启动安装版，截「设置」与「诊断」两页，确认 1.1.1 的开关与发现层文案。"""
from __future__ import annotations

import json
import subprocess
import time
import urllib.request
from pathlib import Path

import psutil

HERE = Path(__file__).resolve().parent.parent
import sys

EXE = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(
    r"C:\Users\50174\dbstudio-build\dist\DropBridge Studio.exe"
)
DATA = HERE / "data"


def kill_all() -> None:
    names = {"DropBridge Studio.exe", "airdrop-studio.exe", "awdld.exe",
             "airbridge_radio.exe", "awdl_netd.exe", "radio_pipe_bridge.exe"}
    for proc in psutil.process_iter(["pid", "name", "cmdline"]):
        try:
            name = proc.info["name"] or ""
            cmd = " ".join(proc.info["cmdline"] or [])
            if name in names or (name.startswith("python") and "receiver.py" in cmd):
                proc.kill()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    time.sleep(3)


def cdp_targets() -> list[dict]:
    with urllib.request.urlopen("http://127.0.0.1:9333/json", timeout=5) as resp:
        return json.loads(resp.read().decode("utf-8"))


def main() -> int:
    kill_all()
    env = dict(**{k: v for k, v in __import__("os").environ.items()})
    env["STUDIO_DEBUG"] = "1"
    proc = subprocess.Popen([str(EXE)], env=env, cwd=str(EXE.parent))
    ws = None
    for _ in range(120):
        time.sleep(1)
        try:
            pages = [p for p in cdp_targets() if p.get("type") == "page"]
            if pages:
                ws = pages[0]["webSocketDebuggerUrl"]
                break
        except Exception:
            continue
    if not ws:
        print("no cdp page")
        proc.kill()
        return 1
    print("ws ok")
    from websocket import create_connection

    conn = create_connection(ws, timeout=30)

    def evaluate(expr: str):
        conn.send(json.dumps({"id": 1, "method": "Runtime.evaluate",
                              "params": {"expression": expr, "awaitPromise": True, "returnByValue": True}}))
        for _ in range(200):
            msg = json.loads(conn.recv())
            if msg.get("id") == 1:
                res = msg.get("result", {}).get("result", {})
                return res.get("value", res.get("description"))
        return None

    def shot(name: str) -> None:
        conn.send(json.dumps({"id": 2, "method": "Page.captureScreenshot", "params": {"format": "png"}}))
        for _ in range(200):
            msg = json.loads(conn.recv())
            if msg.get("id") == 2:
                import base64
                DATA.mkdir(exist_ok=True)
                (DATA / name).write_bytes(base64.b64decode(msg["result"]["data"]))
                print("shot", name)
                return

    phases = []
    for _ in range(180):
        st = evaluate("window.pywebview && window.pywebview.api.state().then(s => s.phase)")
        phases.append(st)
        if st == "ready":
            break
        time.sleep(2)
    print("phase:", phases[-1])
    evaluate("document.querySelector('.rail-btn[data-view=\"settings\"]').click()")
    time.sleep(1.5)
    shot("gui-settings-111.png")
    e = evaluate("JSON.stringify({observe: !!document.querySelector('#setObserve'), tray: !!document.querySelector('#setTray')})")
    print("switches:", e)
    evaluate("document.querySelector('.rail-btn[data-view=\"doctor\"]').click()")
    time.sleep(2)
    evaluate("document.querySelector('#discoveryTable').scrollIntoView({block:'center'})")
    time.sleep(0.8)
    shot("gui-discovery-111.png")
    print("discovery:", evaluate("JSON.stringify(window.__lastState ? null : (document.querySelector('#discoveryTable').innerText))"))
    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
