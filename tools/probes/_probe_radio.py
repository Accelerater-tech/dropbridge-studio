import sys, time
sys.path.insert(0, r"C:\Users\50174\Documents\deepseek-harness\default-workspace\DropBridgeStudio")
from app import config
from app.supervisor import Chain

s = config.Settings()
c = Chain(s)
print("root:", s.root, flush=True)
print("reclaim", c.reclaim(), flush=True)
c.start()
time.sleep(14)
snap = c.snapshot()
radio = [x for x in snap["children"] if x["name"] == "radio"][0]
print("phase", snap["phase"], "| message", snap["message"], "| radio", radio, flush=True)
lines = c.logs("radio", 30)
print("radio lines:", len(lines), flush=True)
for row in lines:
    print("RADIO>", row["text"][:170], flush=True)
c.stop()
