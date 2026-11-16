import subprocess, time, sys, os

exe = r"C:\Users\50174\Desktop\DropBridge\backend\airbridge_radio.exe"
cwd = r"C:\Users\50174\Desktop\DropBridge"
env = dict(os.environ)
env.update({"PYTHONUNBUFFERED": "1", "AIRBRIDGE_LINK_STATS": "1"})
p = subprocess.Popen([exe, "149", "20"], cwd=cwd, env=env,
                     stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                     bufsize=0, creationflags=0x08000000)
start = time.time()
count = 0
while time.time() - start < 20:
    line = p.stdout.readline()
    if not line:
        print("EOF at", round(time.time() - start, 1))
        break
    count += 1
    text = line.decode("utf-8", "replace").rstrip()
    if count <= 40:
        print(round(time.time() - start, 1), text[:150], flush=True)
print("total lines", count, "elapsed", round(time.time() - start, 1))
p.terminate()
