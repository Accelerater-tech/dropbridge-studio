import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PYW = Path(sys.executable).with_name("pythonw.exe")
sys.path.insert(0, str(ROOT / "tools"))
from shot_window import capture  # noqa: E402
import psutil  # noqa: E402

page = sys.argv[1] if len(sys.argv) > 1 else "doctor"
for proc in psutil.process_iter(["name", "cmdline"]):
    try:
        if (proc.info.get("name") or "").lower() == "pythonw.exe" and "app.main" in " ".join(proc.info.get("cmdline") or []):
            proc.kill()
    except (psutil.Error, OSError):
        pass
time.sleep(1.0)
log = open(ROOT / "data" / f"ui-{page}.err.log", "w")
proc = subprocess.Popen([str(PYW), "-m", "app.main", "--page", page], cwd=str(ROOT),
                        stdout=subprocess.DEVNULL, stderr=log, creationflags=0x00000008)
for wait in (8, 12, 16):
    time.sleep(4 if wait > 8 else 8)
    capture("DropBridge Studio", str(ROOT / "data" / f"page-{page}-{wait}.png"))
log.close()
print("pid", proc.pid)
print(Path(ROOT / "data" / f"ui-{page}.err.log").read_text(encoding="utf-8", errors="replace")[-1500:])
