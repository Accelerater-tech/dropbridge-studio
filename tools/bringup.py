"""干净重启并等待链路就绪（看最新会话目录里有没有 receiver 日志），打印结论。"""
import subprocess
import sys
import time
from pathlib import Path

import psutil

STUDIO = Path(__file__).resolve().parent.parent
PYW = Path(r"C:\Users\50174\AppData\Local\Programs\Python\Python312\pythonw.exe")
LOGS = Path(r"C:\Users\50174\Desktop\DropBridge\data\studio\logs")
NAMES = {"airbridge_radio.exe", "radio_pipe_bridge.exe", "awdl_netd.exe", "awdld.exe"}


def kill_all() -> None:
    me = __import__("os").getpid()
    for proc in psutil.process_iter(["pid", "name", "cmdline", "exe"]):
        if proc.info["pid"] == me:
            continue
        name = (proc.info["name"] or "").lower()
        argv = proc.info["cmdline"] or []
        exe = (proc.info["exe"] or "").lower()
        victim = name in NAMES or (
            "app.main" in argv or "receiver.py" in argv
            or ("powershell" in name and any("beacon.ps1" in a for a in argv))
        ) or ("dropbridge" in exe and name.endswith(".exe"))
        if victim:
            try:
                proc.kill()
            except psutil.Error:
                pass
    time.sleep(3)


def position(began: float) -> int:
    return int(time.time() - began)


def main() -> int:
    kill_all()
    before = {p.name for p in LOGS.iterdir()} if LOGS.exists() else set()
    subprocess.Popen([str(PYW), "-m", "app.main"], cwd=str(STUDIO),
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     creationflags=0x00000008)  # DETACHED_PROCESS
    began = time.time()
    deadline = began + 150
    run_dir = None
    while time.time() < deadline:
        time.sleep(3)
        fresh = [d for d in LOGS.iterdir() if d.is_dir() and d.name not in before]
        if not fresh:
            continue
        run_dir = max(fresh, key=lambda p: p.stat().st_mtime)
        marker = run_dir / "receiver.log"
        if marker.exists():
            text = marker.read_text(encoding="utf-8", errors="replace")
            if "receiving as" in text:
                print(f"READY in {position(began)}s dir {run_dir.name}")
                print(text.strip().splitlines()[-1][:120])
                return 0
    print("NOT READY, last dir:", run_dir)
    if run_dir:
        for path in sorted(run_dir.glob("*.log")):
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
            print(f"-- {path.name}: {lines[-1][:120] if lines else '<empty>'}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
