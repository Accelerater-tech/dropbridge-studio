import sys, time
sys.path.insert(0, r"C:\Users\50174\Documents\deepseek-harness\default-workspace\DropBridgeStudio")
from app import config
from app import supervisor as sup

s = config.Settings()
c = sup.Chain(s)
print("root:", s.root, flush=True)
print("reclaim", c.reclaim(), flush=True)
c.start()
start = time.time()
while time.time() - start < 45:
    time.sleep(2)
    snap = c.snapshot()
    nodes = " ".join(f"{n['name']}{'R' if n['ready'] else ('alive' if n['running'] else 'dead')}" for n in snap["children"])
    print(round(time.time() - start), snap["phase"], snap["message"], "|", nodes,
          "| tcp49876", sup._tcp_open(49876), "| addr", (s.data / "awdl_netd.addr").is_file(), flush=True)
    if snap["phase"] in ("ready", "error"):
        break
for name in ("radio", "bridge", "netd", "awdld", "receiver"):
    rows = c.logs(name, 4)
    for row in rows:
        print(name.upper() + ">", row["text"][:150], flush=True)
print("last_error:", c.last_error, flush=True)
c.stop()
