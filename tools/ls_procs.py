import time

import psutil

for proc in psutil.process_iter(["pid", "name", "exe", "create_time"]):
    exe = (proc.info["exe"] or "").replace("\\", "/").lower()
    if "dropbridge" not in exe and "airbridge" not in exe:
        continue
    print(proc.info["pid"], proc.info["name"],
          time.strftime("%H:%M:%S", time.localtime(proc.info["create_time"])),
          exe.split("/")[-1])
