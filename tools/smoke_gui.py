"""GUI 端到端冒烟：冷启动 Studio → 点「启动接收」→ 等就绪 → CDP 截图与断言。"""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import psutil  # noqa: E402
import cdp  # noqa: E402

PYW = Path(sys.executable).with_name("pythonw.exe")


def kill():
    for proc in psutil.process_iter(["name", "cmdline"]):
        try:
            if (proc.info.get("name") or "").lower() == "pythonw.exe" and \
                    "app.main" in " ".join(proc.info.get("cmdline") or []):
                proc.kill()
        except (psutil.Error, OSError):
            pass


def main() -> int:
    page = sys.argv[1] if len(sys.argv) > 1 else "overview"
    out = sys.argv[2] if len(sys.argv) > 2 else "data/gui-ready.png"
    start = "--no-start" not in sys.argv
    kill()
    time.sleep(1.0)
    env = dict(os.environ, STUDIO_DEBUG="1")
    subprocess.Popen([str(PYW), "-m", "app.main"], cwd=str(ROOT), env=env,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     creationflags=0x00000008)
    time.sleep(7)

    session = cdp.Session()
    try:
        if start:
            print("start ->", session.eval(
                "(async()=>{const r=await window.pywebview.api.start();return JSON.stringify(r)})()"))
        deadline = time.time() + 110
        while time.time() < deadline:
            time.sleep(4)
            phase = session.eval(
                "(async()=>{const s=await window.pywebview.api.state();"
                "return s.phase+'|'+s.message+'|'+(s.last_error||'')})()")
            print("  ", phase)
            if isinstance(phase, str) and (phase.startswith("ready") or phase.startswith("error")):
                break
        if page != "overview":
            session.eval(f"window.__studio.open('{page}')")
            time.sleep(2.5)
        session.shot(str(ROOT / out))
        print("phase:", session.eval(
            "(async()=>{const s=await window.pywebview.api.state();"
            "return JSON.stringify({p:s.phase,n:s.children.map(c=>c.name+':'+(c.ready?'ok':c.running?'..':'x'))})})()"))
    finally:
        session.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
