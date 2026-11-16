"""重启 Studio：先杀掉正在跑的实例，再决定是否带调试口冷启动。

    python tools/restart.py            # 普通启动
    python tools/restart.py --debug    # 带 CDP 调试口
    python tools/restart.py --capture  # 控制台输出写到 data/main.err.log
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

import psutil

STUDIO = Path(__file__).resolve().parent.parent
PY = Path(r"C:\Users\50174\AppData\Local\Programs\Python\Python312\python.exe")
PYW = PY.with_name("pythonw.exe")


def kill_running() -> None:
    me = os.getpid()
    for proc in psutil.process_iter(["pid", "name", "cmdline"]):
        if proc.info["pid"] == me:
            continue
        argv = proc.info["cmdline"] or []
        if not argv:
            continue
        if proc.info["name"] not in ("python.exe", "pythonw.exe"):
            continue
        if "-m" in argv and "app.main" in argv and argv.index("app.main") > 0:
            try:
                proc.kill()
                print("killed", proc.info["pid"])
            except psutil.Error:
                pass
    time.sleep(2)


def main() -> int:
    debug = "--debug" in sys.argv
    capture = "--capture" in sys.argv
    kill_running()

    env = dict(os.environ)
    if debug:
        env["STUDIO_DEBUG"] = "1"
    exe = PY if capture else PYW
    kwargs = {"cwd": str(STUDIO), "env": env, "creationflags": 0x00000008}
    if capture:
        handle = open(STUDIO / "data" / "main.err.log", "wb")
        kwargs.update(stdout=handle, stderr=subprocess.STDOUT)
    subprocess.Popen([str(exe), "-m", "app.main"], **kwargs)
    print("launched", "debug" if debug else "clean", "capture" if capture else "")
    return 0


if __name__ == "__main__":
    sys.exit(main())
