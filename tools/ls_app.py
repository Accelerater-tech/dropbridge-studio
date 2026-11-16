import time

import psutil

for proc in psutil.process_iter(["pid", "name", "cmdline", "create_time"]):
    argv = proc.info["cmdline"] or []
    if "-m" in argv and "app.main" in argv:
        print(proc.info["pid"], proc.info["name"],
              time.strftime("%H:%M:%S", time.localtime(proc.info["create_time"])),
              " ".join(argv[:6]))
