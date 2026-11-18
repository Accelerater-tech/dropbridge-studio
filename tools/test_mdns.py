"""mDNS 旁听器的离线自测：解析、计数、转发。

不需要真机、不需要启动链路：
  python tools/test_mdns.py
"""
from __future__ import annotations

import socket
import struct
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import mdns_observe  # noqa: E402


def build_query(name: str, qtype: int = 12) -> bytes:
    """拼一个最小可用的 mDNS 查询包（PTR）。"""
    header = struct.pack(">HHHHHH", 0, 0, 1, 0, 0, 0)
    labels = b"".join(bytes([len(part)]) + part.encode("ascii") for part in name.split(".") if part) + b"\x00"
    return header + labels + struct.pack(">HH", qtype, 1)


def main() -> int:
    failures = []

    # 1) 解析
    packet = build_query("_airdrop._tcp.local")
    names, qtypes, response = mdns_observe.parse_questions(packet)
    print("parse:", names, qtypes, response)
    if names != ["_airdrop._tcp.local"] or qtypes != [12] or response:
        failures.append("parse_questions 输出不对")

    # 2) 旁听 + 转发：observer 监听 15354，upstream 是本地一个假的 netd
    fake_netd = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    fake_netd.bind(("127.0.0.1", 0))
    fake_netd.settimeout(3)
    upstream_port = fake_netd.getsockname()[1]

    observer = mdns_observe.MdnsObserver(listen_port=15354, upstream_port=upstream_port)
    if not observer.start():
        print("observer 起不来:", observer.error)
        return 1
    try:
        fake_receiver = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        fake_receiver.bind(("127.0.0.1", 0))
        fake_receiver.settimeout(3)

        # receiver → observer → netd
        fake_receiver.sendto(packet, ("127.0.0.1", 15354))
        forwarded, _ = fake_netd.recvfrom(9000)
        if not forwarded.startswith(b"\x00\x00"):
            failures.append("上游没收到转发包")

        # netd 回应 → observer → receiver
        reply = struct.pack(">HHHHHH", 0, 0x8400, 0, 1, 0, 0) + forwarded[12:]
        fake_netd.sendto(reply, ("127.0.0.1", 15354))
        back, _ = fake_receiver.recvfrom(9000)
        if back != reply:
            failures.append("回应没有原样回到 receiver")

        time.sleep(0.2)
        snap = observer.snapshot()
        print("snapshot:", {k: snap[k] for k in ("total_queries", "total_responses", "port", "listening")})
        print("recent:", snap["recent"])
        if snap["total_queries"] != 1:
            failures.append(f"查询计数应为 1，实际 {snap['total_queries']}")
        if snap["total_responses"] != 1:
            failures.append(f"回应计数应为 1，实际 {snap['total_responses']}")
        if not snap["names"]:
            failures.append("names 为空")
    finally:
        observer.stop()
        fake_netd.close()

    if failures:
        for item in failures:
            print("FAIL:", item)
        return 1
    print("OK: mDNS 旁听器解析/计数/双向转发都正常")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
