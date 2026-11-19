"""从本机模拟一次 mDNS 查询，验证「receiver ↔ 旁听器 ↔ netd」这条发现链是通的。

做法：像 receiver 一样把 `_airdrop._tcp.local` 的 PTR 查询发到 15354，
旁听器会转给 netd 广播出去；如果本机的 responder 收到并正常回答，
我们就能在同一个 socket 上收到应答（说明发现层没问题）。
"""
from __future__ import annotations

import socket
import struct
import sys
import time
import uuid

TARGET = ("127.0.0.1", int(sys.argv[1]) if len(sys.argv) > 1 else 15354)
NAME = "_airdrop._tcp.local"


def build_query(name: str, qtype: int = 12) -> bytes:
    header = struct.pack("!HHHHHH", 0, 0, 1, 0, 0, 0)
    question = b""
    for label in name.split("."):
        raw = label.encode()
        question += bytes([len(raw)]) + raw
    question += b"\x00" + struct.pack("!HH", qtype, 1)
    return header + question


def read_name(data: bytes, offset: int) -> tuple[str, int]:
    labels = []
    while True:
        length = data[offset]
        if length == 0:
            return ".".join(labels), offset + 1
        if length & 0xC0:
            pointer = struct.unpack_from("!H", data, offset)[0] & 0x3FFF
            nested, _ = read_name(data, pointer)
            labels.append(nested)
            return ".".join(labels), offset + 2
        labels.append(data[offset + 1:offset + 1 + length].decode("utf-8", "replace"))
        offset += 1 + length


def main() -> int:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("127.0.0.1", 0))
    sock.settimeout(4)
    probe = build_query(NAME, 12)
    sock.sendto(probe, TARGET)
    print(f"query {NAME} -> {TARGET[0]}:{TARGET[1]} from port {sock.getsockname()[1]}")
    seen = []
    deadline = time.monotonic() + 4.5
    while time.monotonic() < deadline:
        try:
            data, addr = sock.recvfrom(9000)
        except socket.timeout:
            break
        if len(data) < 12:
            continue
        flags, qd, an, ns, ar = struct.unpack_from("!HHHHH", data, 2)
        if not an + ns + ar:
            continue
        names = []
        offset = 12
        for _ in range(qd):
            _, offset = read_name(data, offset)
            offset += 4
        for _ in range(an + ns + ar):
            name, offset = read_name(data, offset)
            names.append(name)
            if offset + 10 > len(data):
                break
            _, _, _, rdlen = struct.unpack_from("!HHIH", data, offset)
            offset += 10 + rdlen
        seen.append((addr, names))
        print(f"  answer from {addr[0]}:{addr[1]}: {len(names)} records -> {names[:6]}")

    if not seen:
        print("NO ANSWER — 发现层这条链是断的（netd 没把查询广播出去，或 responder 没回）")
        return 1
    hits = [n for _, names in seen for n in names if "_airdrop" in n]
    print(f"OK: {len(seen)} 个应答包, {len(hits)} 条 _airdrop 记录")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
