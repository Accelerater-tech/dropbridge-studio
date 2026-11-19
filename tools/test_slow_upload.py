"""慢链路回归：模拟 iPad 那种「传一小段、停几十秒、再慢慢传」的发送端。

    python tools/test_slow_upload.py [--stall 45] [--rate 20] [--size 1.2]

真机 iPad 在 AWDL 上丢了包会按 1/2/4/8/16/32 秒退避重传，旧版接收器
30 秒没有新字节就回 408 把连接掐了。这个脚本用同样的节奏验证：中断
45 秒之后仍能继续传完并落盘。
"""
from __future__ import annotations

import argparse
import gzip
import os
import plistlib
import socket
import ssl
import sys
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fake_sender import cpio_newc  # noqa: E402

HOST, PORT = "127.0.0.1", 8771


def read_response(sock) -> tuple[int, bytes]:
    buffer = b""
    while b"\r\n\r\n" not in buffer:
        chunk = sock.recv(4096)
        if not chunk:
            raise RuntimeError("response cut off")
        buffer += chunk
    head, _, rest = buffer.partition(b"\r\n\r\n")
    status = int(head.split()[1])
    length = 0
    for line in head.split(b"\r\n")[1:]:
        key, _, value = line.partition(b":")
        if key.strip().lower() == b"content-length":
            length = int(value.strip())
    body = rest
    while len(body) < length:
        body += sock.recv(65536)
    return status, body[:length]


def post_chunked(sock, path: str, body: bytes, headers: dict[str, str]) -> tuple[int, bytes]:
    lines = [
        f"POST {path} HTTP/1.1",
        f"Host: {HOST}:{PORT}",
        "User-Agent: AirDrop/1.0",
        "Connection: keep-alive",
        "Transfer-Encoding: chunked",
    ]
    lines += [f"{key}: {value}" for key, value in headers.items()]
    sock.sendall(("\r\n".join(lines) + "\r\n\r\n").encode())
    for start in range(0, len(body), 4096):
        piece = body[start:start + 4096]
        sock.sendall(f"{len(piece):X}\r\n".encode() + piece + b"\r\n")
    sock.sendall(b"0\r\n\r\n")
    return read_response(sock)


def stream_slow(sock, body: bytes, rate_kib: float, stall_after: float, stall_seconds: float) -> float:
    """Push the body chunk by chunk, stalling in the middle like a real link."""
    step = 16 * 1024
    pause = step / (rate_kib * 1024)
    started = time.monotonic()
    stalled = False
    sent = 0
    for start in range(0, len(body), step):
        piece = body[start:start + step]
        sock.sendall(f"{len(piece):X}\r\n".encode() + piece + b"\r\n")
        sent += len(piece)
        if not stalled and sent >= len(body) * stall_after:
            stalled = True
            print(f"  stalling {stall_seconds:.0f}s at {sent} bytes")
            time.sleep(stall_seconds)
        else:
            time.sleep(pause)
        if sent % (256 * 1024) < step:
            print(f"  {sent}/{len(body)} bytes ({time.monotonic() - started:.0f}s)")
    sock.sendall(b"0\r\n\r\n")
    return time.monotonic() - started


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--stall", type=float, default=45.0, help="中途停多少秒")
    parser.add_argument("--rate", type=float, default=20.0, help="每秒钟发多少 KiB")
    parser.add_argument("--size", type=float, default=1.2, help="文件大小（MB，随机数据不可压缩）")
    parser.add_argument("--host", default=HOST)
    args = parser.parse_args()

    payload = os.urandom(int(args.size * 1024 * 1024))
    name = f"slow-{uuid.uuid4().hex[:6]}.bin"
    archive = gzip.compress(cpio_newc([(name, payload)]), 1)
    # gzip 会把随机数据撑大一点点，实际传的就是 archive 的长度
    print(f"archive {len(archive) / 1048576:.2f} MB, stall {args.stall:.0f}s at 40%, "
          f"rate ~{args.rate:.0f} KiB/s")

    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    context.set_ciphers("DEFAULT:@SECLEVEL=1")
    raw = socket.create_connection((args.host, PORT), timeout=30)
    tls = context.wrap_socket(raw, server_hostname=args.host)
    print("TLS", tls.version(), tls.cipher()[0])

    discover = plistlib.dumps({
        "SenderComputerName": "Slow iPad",
        "SenderModelName": "iPad",
        "SenderRecordData": b"",
        "SenderMediaCapabilities": b'{"Version":1}',
    }, fmt=plistlib.FMT_BINARY)
    print("Discover ->", post_chunked(tls, "/Discover", discover,
                                     {"Content-Type": "application/octet-stream"})[0])

    ask = plistlib.dumps({
        "SenderComputerName": "Slow iPad",
        "SenderModelName": "iPad",
        "Files": [{"FileName": name, "FileType": "public.data",
                   "FileSize": len(payload), "FileIsDirectory": False}],
        "Items": [],
        "TransferType": {"files": {}},
        "SenderRecordData": b"",
    }, fmt=plistlib.FMT_BINARY)
    status, answer = post_chunked(tls, "/Ask", ask, {"Content-Type": "application/octet-stream"})
    print("Ask ->", status)
    if status != 200:
        print("rejected:", answer[:300])
        return 1

    transfer_id = str(uuid.uuid4()).upper()
    header = "\r\n".join([
        f"POST /Upload HTTP/1.1",
        f"Host: {HOST}:{PORT}",
        "User-Agent: AirDrop/1.0",
        "Connection: keep-alive",
        "Transfer-Encoding: chunked",
        f"TransferID: {transfer_id}",
        f"TotalBytes: {len(archive)}",
        "Content-Type: application/x-dvzip",
    ]) + "\r\n\r\n"
    tls.sendall(header.encode())
    took = stream_slow(tls, archive, args.rate, 0.4, args.stall)
    status, body = read_response(tls)
    print(f"Upload -> {status} after {took:.0f}s {body[:200]!r}")
    tls.close()
    return 0 if status == 200 else 1


if __name__ == "__main__":
    raise SystemExit(main())
