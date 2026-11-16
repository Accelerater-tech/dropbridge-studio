"""故意留一个孤儿 radio，再让 Studio 启动，验证它会先清残留再拉起全链路。"""
import subprocess
import sys
import time
from pathlib import Path

import psutil

ROOT = Path(r"C:\Users\50174\Desktop\DropBridge")
PY = Path(r"C:\Users\50174\AppData\Local\Programs\Python\Python312\python.exe")
STUDIO = Path(r"C:\Users\50174\Documents\deepseek-harness\default-workspace\DropBridgeStudio")
LOGS = ROOT / "data" / "studio" / "logs"


def kill_all() -> None:
    for proc in psutil.process_iter(["pid", "name", "cmdline", "exe"]):
        name = (proc.info["name"] or "").lower()
        argv = proc.info["cmdline"] or []
        exe = (proc.info["exe"] or "").lower()
        if name in {"airbridge_radio.exe", "radio_pipe_bridge.exe", "awdl_netd.exe", "awdld.exe"} \
                or "app.main" in argv or "receiver.py" in argv \
                or ("powershell" in name and any("beacon.ps1" in a for a in argv)):
            try:
                proc.kill()
            except psutil.Error:
                pass
    time.sleep(2.5)


def main() -> int:
    kill_all()
    orphan = subprocess.Popen([str(ROOT / "backend" / "airbridge_radio.exe"), "149", "20"],
                              cwd=str(ROOT), stdout=subprocess.DEVNULL,
                              stderr=subprocess.DEVNULL)
    print("孤儿 radio pid", orphan.pid)
    time.sleep(6)

    subprocess.Popen([str(PY.with_name("pythonw.exe")), "-m", "app.main"], cwd=str(STUDIO),
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     creationflags=0x00000008)
    deadline = time.time() + 160
    while time.time() < deadline:
        time.sleep(3)
        logs = sorted(LOGS.glob("*/*.log"), key=lambda p: p.stat().st_mtime, reverse=True)
        if not logs:
            continue
        run_dir = logs[0].parent
        marker = run_dir / "receiver.log"
        if marker.exists():
            text = marker.read_text(encoding="utf-8", errors="replace")
            if "receiving as" in text:
                print("READY dir", run_dir.name, "| orphan alive:", orphan.poll() is None)
                return 0
    print("FAILED")
    for path in sorted(logs[0].parent.glob("*.log")) if logs else []:
        print(path.name, path.read_text(encoding="utf-8", errors="replace").splitlines()[-1:])
    return 1


if __name__ == "__main__":
    sys.exit(main())
