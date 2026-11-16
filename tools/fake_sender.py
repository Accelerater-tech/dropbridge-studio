"""假 AirDrop 发送端：只用来验证接收链路（TLS → Discover → Ask → Upload）。

    python tools/fake_sender.py --file 图片.jpg [--name 测试机]

真机 iPhone 不参与，也能确认「接收 → 落盘 → 界面显示」这条链条是通的。
"""
from __future__ import annotations

import argparse
import gzip
import plistlib
import socket
import ssl
import sys
import time
import uuid
from pathlib import Path

HOST, PORT = "127.0.0.1", 8771


def cpio_newc(entries: list[tuple[str, bytes]]) -> bytes:
    """最小可用的 newc 归档（receiver 侧用 cpio.read_entries 读）。"""
    out = bytearray()
    ino = 1
    for name, data in entries:
        raw = name.encode() + b"\0"
        fields = [ino, 0o100644, 0, 0, 1, int(time.time()), len(data), 0, 0, 0, 0, len(raw), 0]
        out += b"070701" + b"".join(b"%08X" % value for value in fields)
        out += raw
        out += b"\0" * (-len(out) % 4)
        out += data
        out += b"\0" * (-len(out) % 4)
        ino += 1
    trailer = b"TRAILER!!!\0"
    fields = [0, 0, 0, 0, 1, 0, 0, 0, 0, 0, 0, len(trailer), 0]
    out += b"070701" + b"".join(b"%08X" % value for value in fields)
    out += trailer
    out += b"\0" * (-len(out) % 4)
    return bytes(out)


def post(sock, path: str, body: bytes, headers: dict[str, str]) -> tuple[int, bytes]:
    lines = [f"POST {path} HTTP/1.1", f"Host: {HOST}:{PORT}",
             "User-Agent: AirDrop/1.0", "Connection: keep-alive"]
    lines += [f"{key}: {value}" for key, value in headers.items()]
    lines.append(f"Content-Length: {len(body)}")
    request = ("\r\n".join(lines) + "\r\n\r\n").encode() + body
    sock.sendall(request)

    buffer = b""
    while b"\r\n\r\n" not in buffer:
        chunk = sock.recv(4096)
        if not chunk:
            raise RuntimeError(f"no response for {path}")
        buffer += chunk
    head, _, rest = buffer.partition(b"\r\n\r\n")
    status = int(head.split()[1])
    length = 0
    for line in head.split(b"\r\n")[1:]:
        key, _, value = line.partition(b":")
        if key.strip().lower() == b"content-length":
            length = int(value.strip())
    body_out = rest
    while len(body_out) < length:
        body_out += sock.recv(65536)
    return status, body_out[:length]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--file", required=True, help="要“投送”的本地文件")
    parser.add_argument("--name", default="Fake iPhone", help="发送方名字")
    parser.add_argument("--model", default="iPhone14,2")
    parser.add_argument("--host", default=HOST)
    args = parser.parse_args()

    source = Path(args.file)
    payload = source.read_bytes()
    kind = {".jpg": "public.jpeg", ".jpeg": "public.jpeg", ".png": "public.png",
            ".mov": "com.apple.quicktime-movie", ".pdf": "com.adobe.pdf",
            ".zip": "public.zip-archive", ".txt": "public.plain-text"}.get(
        source.suffix.lower(), "public.data")

    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    context.set_ciphers("DEFAULT:@SECLEVEL=1")

    raw = socket.create_connection((args.host, PORT), timeout=30)
    tls = context.wrap_socket(raw, server_hostname=args.host)
    print(f"TLS {tls.version()} {tls.cipher()[0]}")

    discover = plistlib.dumps({
        "SenderComputerName": args.name,
        "SenderModelName": args.model,
        "SenderRecordData": b"",
        "SenderMediaCapabilities": b"{\"Version\":1}",
    }, fmt=plistlib.FMT_BINARY)
    print("Discover ->", post(tls, "/Discover", discover,
                              {"Content-Type": "application/octet-stream"})[0])

    ask = plistlib.dumps({
        "SenderComputerName": args.name,
        "SenderModelName": args.model,
        "Files": [{"FileName": source.name, "FileType": kind,
                   "FileSize": len(payload), "FileBomb": False}],
        "Items": [source.name],
        "TransferType": [kind],
        "SenderRecordData": b"",
    }, fmt=plistlib.FMT_BINARY)
    status, answer = post(tls, "/Ask", ask, {"Content-Type": "application/octet-stream"})
    print("Ask ->", status)
    if status != 200:
        print("rejected:", answer[:300])
        return 1

    archive = gzip.compress(cpio_newc([(source.name, payload)]), 6)
    transfer_id = uuid.uuid4().hex.upper()
    status, answer = post(tls, "/Upload", archive, {
        "Content-Type": "application/x-cpio",
        "TransferID": transfer_id,
        "TotalBytes": str(len(archive)),
    })
    print("Upload ->", status, answer[:200])
    return 0 if status == 200 else 1


if __name__ == "__main__":
    sys.exit(main())
