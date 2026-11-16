"""逐页冷启动 UI 并截图（不需要把窗口拿到前台）。"""
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PYW = Path(sys.executable).with_name("pythonw.exe")
sys.path.insert(0, str(ROOT / "tools"))
from shot_window import capture  # noqa: E402

PAGES = sys.argv[1:] or ["transfers", "logs", "doctor", "settings"]


def kill_studio() -> None:
    import psutil
    for proc in psutil.process_iter(["name", "cmdline"]):
        try:
            if (proc.info.get("name") or "").lower() != "pythonw.exe":
                continue
            cmd = " ".join(proc.info.get("cmdline") or [])
            if "app.main" in cmd:
                proc.kill()
        except (psutil.Error, OSError):
            continue


for page in PAGES:
    kill_studio()
    time.sleep(0.8)
    subprocess.Popen([str(PYW), "-m", "app.main", "--page", page], cwd=str(ROOT),
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     creationflags=0x00000008)  # DETACHED_PROCESS
    time.sleep(6.5)
    capture("DropBridge Studio", str(ROOT / "data" / f"page-{page}.png"))
print("done")
