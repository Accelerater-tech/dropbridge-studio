"""离线验证 diag.export_report 能跑通（不需要 GUI）。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import config, diag  # noqa: E402


class FakeChain:
    run_dir = Path("C:/Users/50174/Desktop/DropBridge/data/studio/logs/20261116-112126")

    def snapshot(self):
        return {"phase": "ready", "transfers": [{"name": "self-test-112018.png", "size": 5300}]}

    def logs(self, name, limit=400):
        return [f"<{name} line>"]


settings = config.Settings.load()
target = Path("C:/Users/50174/Documents/deepseek-harness/default-workspace/DropBridgeStudio/data/report-test.json")
path = diag.export_report(settings, FakeChain(), target)
size = path.stat().st_size
import json  # noqa: E402

data = json.loads(path.read_text(encoding="utf-8"))
print("bytes", size, "keys", sorted(data))
print("disk_logs", {k: len(v) for k, v in data["disk_logs"].items()})
print("notable", data["notable"])
