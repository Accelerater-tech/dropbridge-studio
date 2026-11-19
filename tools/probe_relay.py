"""独立复现旁听器的转发：15360 -> 15353，看 netd 会不会回、回的包能不能转回来。

不依赖正在运行的 App，用来判断「旁听逻辑本身」有没有问题。
"""
from __future__ import annotations

import socket
import struct
import threading
import time

LISTEN = ("127.0.0.1", 15360)
UPSTREAM = ("127.0.0.1", 15353)


def build_query(name: str, qtype: int = 12) -> bytes:
    header = struct.pack("!HHHHHH", 0, 0, 1, 0, 0, 0)
    body = b"".join(bytes([len(part)]) + part.encode() for part in name.split("."))
    return header + body + b"\x00" + struct.pack("!HH", qtype, 1)


def main() -> int:
    server = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind(LISTEN)
    server.settimeout(0.3)
    receiver = {"addr": None}
    stats = {"fwd": 0, "back": 0, "err": ""}

    def loop() -> None:
        while True:
            try:
                packet, addr = server.recvfrom(9000)
            except socket.timeout:
                continue
            except OSError:
                return
            if addr == UPSTREAM:
                stats["back"] += 1
                if receiver["addr"]:
                    server.sendto(packet, receiver["addr"])
                continue
            receiver["addr"] = addr
            try:
                server.sendto(packet, UPSTREAM)
                stats["fwd"] += 1
            except OSError as error:
                stats["err"] = str(error)

    threading.Thread(target=loop, daemon=True).start()

    client = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    client.bind(("127.0.0.1", 0))
    client.settimeout(3)
    client.sendto(build_query("_airdrop._tcp.local"), LISTEN)
    try:
        data, addr = client.recvfrom(9000)
        print(f"got {len(data)} bytes back from {addr}")
        ok = True
    except socket.timeout:
        print("no answer")
        ok = False
    time.sleep(0.5)
    print("stats:", stats)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
