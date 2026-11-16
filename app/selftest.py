"""自测：不借 iPhone，自己走一遍 Discover → Ask → Upload。

界面上「自测接收链路」按钮就是它。链路没起来时直接报错，链路正常的
话十几毫秒就能跑完，并把收到的文件丢进「传输」页——用户由此能分清
「电脑这边是好的」和「手机上哪里不对」。
"""
from __future__ import annotations

import gzip
import io
import plistlib
import socket
import ssl
import time
import uuid
from pathlib import Path

HOST = "127.0.0.1"
PORT = 8771


def _cpio(entries: list[tuple[str, bytes]]) -> bytes:
    out = bytearray()
    for ino, (name, data) in enumerate(entries, start=1):
        raw = name.encode() + b"\0"
        fields = [ino, 0o100644, 0, 0, 1, int(time.time()), len(data),
                  0, 0, 0, 0, len(raw), 0]
        out += b"070701" + b"".join(b"%08X" % value for value in fields) + raw
        out += b"\0" * (-len(out) % 4)
        out += data
        out += b"\0" * (-len(out) % 4)
    trailer = b"TRAILER!!!\0"
    fields = [0, 0, 0, 0, 1, 0, 0, 0, 0, 0, 0, len(trailer), 0]
    out += b"070701" + b"".join(b"%08X" % value for value in fields) + trailer
    out += b"\0" * (-len(out) % 4)
    return bytes(out)


def _sample_png() -> bytes:
    """画一张一眼能认出来的图，避免和用户自己的文件混淆。"""
    from PIL import Image, ImageDraw

    image = Image.new("RGB", (720, 480), (16, 22, 38))
    draw = ImageDraw.Draw(image)
    draw.ellipse((60, 90, 420, 450), fill=(96, 165, 250))
    draw.rounded_rectangle((470, 140, 660, 380), radius=24, fill=(244, 114, 182))
    draw.text((70, 30), "DropBridge Studio self-test", fill=(226, 232, 240))
    buffer = io.BytesIO()
    image.save(buffer, "PNG")
    return buffer.getvalue()


def _post(sock, path: str, body: bytes, headers: dict[str, str]) -> tuple[int, bytes]:
    lines = [f"POST {path} HTTP/1.1", f"Host: {HOST}:{PORT}",
             "User-Agent: AirDrop/1.0", "Connection: keep-alive"]
    lines += [f"{key}: {value}" for key, value in headers.items()]
    lines.append(f"Content-Length: {len(body)}")
    sock.sendall(("\r\n".join(lines) + "\r\n\r\n").encode() + body)

    buffer = b""
    while b"\r\n\r\n" not in buffer:
        chunk = sock.recv(4096)
        if not chunk:
            raise RuntimeError(f"{path} 没有响应")
        buffer += chunk
    head, _, rest = buffer.partition(b"\r\n\r\n")
    status = int(head.split()[1])
    length = 0
    for line in head.split(b"\r\n")[1:]:
        key, _, value = line.partition(b":")
        if key.strip().lower() == b"content-length":
            length = int(value.strip())
    while len(rest) < length:
        rest += sock.recv(65536)
    return status, rest[:length]


def run(outdir: str | Path, name: str = "自检") -> dict:
    """返回 {"ok": bool, "steps": [...], "file": <落盘路径>, "error": str}"""
    steps: list[dict] = []

    def step(label: str, ok: bool, detail: str = "") -> None:
        steps.append({"label": label, "ok": ok, "detail": detail})

    try:
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
        context.set_ciphers("DEFAULT:@SECLEVEL=1")
        raw = socket.create_connection((HOST, PORT), timeout=8)
    except OSError as error:
        return {"ok": False, "steps": steps,
                "error": f"连不上接收端 127.0.0.1:{PORT}（链路还没就绪？）：{error}"}

    try:
        tls = context.wrap_socket(raw, server_hostname=HOST)
        step("TLS 握手", True, f"{tls.version()} / {tls.cipher()[0]}")

        discover = plistlib.dumps({
            "SenderComputerName": name,
            "SenderModelName": "MacBookPro18,3",
            "SenderRecordData": b"",
            "SenderMediaCapabilities": b'{"Version":1}',
        }, fmt=plistlib.FMT_BINARY)
        status, _ = _post(tls, "/Discover", discover,
                          {"Content-Type": "application/octet-stream"})
        step("Discover", status == 200, f"HTTP {status}")

        payload = _sample_png()
        file_name = f"self-test-{time.strftime('%H%M%S')}.png"
        ask = plistlib.dumps({
            "SenderComputerName": name,
            "SenderModelName": "MacBookPro18,3",
            "Files": [{"FileName": file_name, "FileType": "public.png",
                       "FileSize": len(payload), "FileBomb": False}],
            "Items": [file_name],
            "TransferType": ["public.png"],
            "SenderRecordData": b"",
        }, fmt=plistlib.FMT_BINARY)
        status, body = _post(tls, "/Ask", ask,
                             {"Content-Type": "application/octet-stream"})
        step("Ask", status == 200, f"HTTP {status}" + ("" if status == 200 else f" {body[:80]!r}"))

        archive = gzip.compress(_cpio([(file_name, payload)]), 6)
        status, body = _post(tls, "/Upload", archive, {
            "Content-Type": "application/x-cpio",
            "TransferID": uuid.uuid4().hex.upper(),
            "TotalBytes": str(len(archive)),
        })
        step("Upload", status == 200, f"HTTP {status}")

        target = Path(outdir) / file_name
        for _ in range(30):
            if target.is_file():
                break
            time.sleep(0.1)
        ok = target.is_file()
        step("落盘", ok, str(target) if ok else "接收目录里没找到文件")
        return {"ok": ok and all(item["ok"] for item in steps),
                "steps": steps, "file": str(target) if ok else "", "error": ""}
    except Exception as error:  # 自测失败要如实告诉用户
        return {"ok": False, "steps": steps, "error": f"{type(error).__name__}: {error}"}
    finally:
        for stream in (locals().get("tls"), raw):
            try:
                if stream is not None:
                    stream.close()
            except Exception:
                pass
